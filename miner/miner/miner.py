from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .aidev import AIDevClient, create_aidev_client
from .db import Database
from .models import Organization, Repository

logger = logging.getLogger(__name__)

@dataclass
class MinerConfig:
    """Toda la config que necesita el miner, cargada desde env/archivo."""

    github_token: str
    clone_root: Path
    db_path: str

    clone_workers: int = 5
    skip_archived: bool = False
    visibility: str = "all"
    clone_timeout: int = 600
    clone_depth: int | None = None
    repo_limit: int = 50
    repo_recent_days: int = 30
    continuous: bool = False
    run_interval_s: int = 3600

    org_filter: list[str] | None = None
    repo_min_stars: int = 0

    @classmethod
    def from_env(cls) -> MinerConfig:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise OSError("Se requiere GITHUB_TOKEN o GH_TOKEN en el entorno.")

        org_filter: list[str] | None = None
        org_filter_str = os.environ.get("AIDEV_ORG_FILTER", "") or os.environ.get("GITHUB_ORG", "")
        if org_filter_str:
            org_filter = [o.strip() for o in org_filter_str.split(",") if o.strip()]

        return cls(
            github_token=token,
            clone_root=Path(os.environ.get("CLONE_ROOT", "/data/repos")),
            db_path=os.environ.get("DB_PATH", "/data/secpipeline.json"),
            clone_workers=int(os.environ.get("CLONE_WORKERS", "5")),
            skip_archived=os.environ.get("SKIP_ARCHIVED", "false").lower() == "true",
            visibility=os.environ.get("REPO_VISIBILITY", "all"),
            clone_timeout=int(os.environ.get("CLONE_TIMEOUT", "600")),
            clone_depth=_parse_depth(os.environ.get("CLONE_DEPTH")),
            repo_limit=int(os.environ.get("REPO_LIMIT", "50")),
            repo_recent_days=int(os.environ.get("REPO_RECENT_DAYS", "30")),
            continuous=os.environ.get("RUN_CONTINUOUS", "false").lower() == "true",
            run_interval_s=int(os.environ.get("RUN_INTERVAL_SECONDS", "3600")),
            org_filter=org_filter,
            repo_min_stars=int(os.environ.get("AIDEV_REPO_MIN_STARS", "0")),
        )


def _parse_depth(value: str | None) -> int | None:
    if value is None or value.lower() in ("none", "full", ""):
        return None
    return int(value)


def _normalize_aidev_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Convierte una fila del dataset AIDev al formato de la GitHub API.

    El dataset AIDev es un snapshot de la API de GitHub, por lo que la mayoría
    de campos son idénticos. Este helper rellena campos que pueden faltar.
    """
    owner = row.get("owner")
    if not owner or not isinstance(owner, dict):
        return None

    owner_login = owner.get("login")
    name = row.get("name")
    if not owner_login or not name:
        return None

    full_name = row.get("full_name") or f"{owner_login}/{name}"
    clone_url = row.get("clone_url") or f"https://github.com/{full_name}.git"

    return {
        **row,
        "full_name": full_name,
        "clone_url": clone_url,
        "forks_count": row.get("forks_count") or row.get("forks", 0),
    }

class GitHubClient:

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._limiter = asyncio.Semaphore(10)

    async def preflight_check(self) -> None:
        """Valida el token de GitHub antes de empezar. Falla rápido con mensaje claro."""
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            r = await client.get(f"{self.BASE_URL}/rate_limit")
            if r.status_code == 401:
                raise RuntimeError(
                    "❌  Token de GitHub inválido o expirado.\n"
                    "    Verificá GITHUB_TOKEN en /workspace/.env (sin comillas)."
                )
            r.raise_for_status()
            rate = r.json()["resources"]["core"]
            logger.info(
                f"✅  Token válido — rate limit: {rate['remaining']}/{rate['limit']} "
                f"requests disponibles"
            )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs: Any
    ) -> httpx.Response:
        async with self._limiter:
            response = await client.get(url, **kwargs)

            if response.status_code == 429 or (
                response.status_code == 403
                and "rate limit" in response.text.lower()
            ):
                reset_at = int(response.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset_at - int(datetime.now(UTC).timestamp()), 1)
                logger.warning(f"Rate limit alcanzado. Esperando {wait}s…")
                await asyncio.sleep(wait)
                response = await client.get(url, **kwargs)

            response.raise_for_status()
            return response

@dataclass
class CloneResult:
    repo_full_name: str
    success: bool
    clone_path: Path | None = None
    commit_sha: str | None = None
    error: str | None = None


async def clone_or_update_repo(
    repo: Repository,
    clone_root: Path,
    token: str,
    depth: int | None,
    timeout: int,
) -> CloneResult:
    dest = clone_root / repo.org_name / repo.name
    clone_url = _auth_clone_url(repo.clone_url, token)

    try:
        if (dest / ".git").exists():
            await _git_fetch(dest, timeout)
        else:
            if dest.exists():
                logger.warning(f"[{repo.full_name}] Directorio sin .git encontrado, limpiando…")
                shutil.rmtree(dest)
            dest.mkdir(parents=True, exist_ok=True)
            await _git_clone(clone_url, dest, depth, timeout)

        sha = await _get_head_sha(dest)
        return CloneResult(
            repo_full_name=repo.full_name,
            success=True,
            clone_path=dest,
            commit_sha=sha,
        )

    except Exception as exc:
        logger.error(f"[{repo.full_name}] Error al clonar: {exc}")
        return CloneResult(
            repo_full_name=repo.full_name,
            success=False,
            error=str(exc),
        )


def _auth_clone_url(clone_url: str, token: str) -> str:
    return clone_url.replace("https://", f"https://x-access-token:{token}@")


async def _git_clone(url: str, dest: Path, depth: int | None, timeout: int) -> None:
    cmd = ["git", "clone"]
    if depth is not None:
        cmd += ["--depth", str(depth)]
    cmd += [url, str(dest)]
    await _run_git(cmd, timeout=timeout, stream_progress=False)


async def _git_fetch(dest: Path, timeout: int) -> None:
    cmd = ["git", "-C", str(dest), "fetch", "--quiet", "--all", "--prune"]
    await _run_git(cmd, timeout=timeout, stream_progress=False)


async def _get_head_sha(dest: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(dest), "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


_PROGRESS_KEYWORDS = (
    "receiving objects",
    "resolving deltas",
    "counting objects",
    "compressing objects",
    "checking out files",
    "remote:",
    "cloning into",
)


async def _run_git(cmd: list[str], timeout: int, stream_progress: bool = False) -> None:
    safe_cmd = [c if "x-access-token" not in c else "***" for c in cmd]
    logger.debug(f"$ {' '.join(safe_cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )

    stderr_chunks: list[bytes] = []

    async def _stream() -> None:
        assert proc.stderr is not None
        last_logged = ""
        while True:
            chunk = await proc.stderr.read(256)
            if not chunk:
                break
            stderr_chunks.append(chunk)
            if stream_progress:
                text = chunk.decode(errors="replace")
                # git usa \r para sobrescribir la línea — separamos por \r y \n
                for part in re.split(r"[\r\n]+", text):
                    part = part.strip()
                    if not part or part == last_logged:
                        continue
                    if any(kw in part.lower() for kw in _PROGRESS_KEYWORDS):
                        logger.info(f"[clone]    ↳ {part}")
                        last_logged = part

    try:
        stream_task = asyncio.create_task(_stream())
        await asyncio.wait_for(proc.wait(), timeout=timeout)
        await stream_task
    except TimeoutError as err:
        proc.kill()
        raise TimeoutError(f"Git timeout después de {timeout}s") from err

    if proc.returncode != 0:
        stderr_str = b"".join(stderr_chunks).decode(errors="replace").strip()
        stderr_str = stderr_str.replace(
            next((c for c in cmd if "x-access-token" in c), ""), "***"
        )
        raise RuntimeError(f"git falló (rc={proc.returncode}): {stderr_str}")

class GitHubMiner:

    def __init__(self, config: MinerConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self.client = GitHubClient(config.github_token)
        self.aidev_client: AIDevClient | None = None

    async def run(self) -> tuple[dict[str, Any], list[Repository]]:
        """Carga organizaciones del dataset AIDev y selecciona repos para el pipeline."""
        logger.info("Cargando repositorios desde el dataset AIDev (HuggingFace)")
        self.aidev_client = create_aidev_client()

        all_orgs = self.aidev_client.list_organizations(min_stars=self.config.repo_min_stars)
        logger.info(f"Organizaciones en AIDev: {len(all_orgs)}")

        if self.config.org_filter:
            org_filter_set = set(self.config.org_filter)
            all_orgs = [o for o in all_orgs if o.login in org_filter_set]
            logger.info(f"Organizaciones tras filtro: {len(all_orgs)}")

        if not all_orgs:
            raise RuntimeError("No se encontraron organizaciones en AIDev con los filtros especificados")

        all_repos: list[Repository] = []
        for aidev_org in all_orgs:
            logger.info(f"Procesando owner: {aidev_org.login} ({aidev_org.repo_count} repos en AIDev)")
            try:
                org = await self.db.upsert_organization(Organization(
                    name=aidev_org.login,
                    url=f"https://github.com/{aidev_org.login}",
                ))
                repos = await self._collect_repos_from_aidev(org, aidev_org.login)
                all_repos.extend(repos)
                logger.info(f"  → {len(repos)} repos seleccionados de {aidev_org.login}")
            except Exception as e:
                logger.error(f"Error procesando owner {aidev_org.login}: {e}")
                continue

        logger.info(f"Total repos seleccionados: {len(all_repos)}")
        return {
            "org": f"AIDev-{len(all_orgs)}-orgs",
            "repos_selected": len(all_repos),
            "repo_limit": self.config.repo_limit,
            "aidev_orgs_processed": len(all_orgs),
            "timestamp": datetime.now(UTC).isoformat(),
        }, all_repos

    async def stream_repos(
        self, out_q: asyncio.Queue[Repository | None]
    ) -> dict[str, Any]:
        """Descubre repos del dataset AIDev y los pone en out_q a medida que los encuentra.
        Siempre envía None al final como sentinel, incluso si falla."""
        logger.info("Cargando repositorios desde el dataset AIDev (HuggingFace)")
        self.aidev_client = create_aidev_client()

        all_orgs = self.aidev_client.list_organizations(min_stars=self.config.repo_min_stars)
        logger.info(f"Organizaciones en AIDev: {len(all_orgs)}")

        if self.config.org_filter:
            org_filter_set = set(self.config.org_filter)
            all_orgs = [o for o in all_orgs if o.login in org_filter_set]
            logger.info(f"Organizaciones tras filtro: {len(all_orgs)}")

        total_repos = 0
        orgs_processed = 0
        try:
            if not all_orgs:
                raise RuntimeError(
                    "No se encontraron organizaciones en AIDev con los filtros especificados"
                )

            for aidev_org in all_orgs:
                logger.info(
                    f"Procesando owner: {aidev_org.login} ({aidev_org.repo_count} repos en AIDev)"
                )
                try:
                    org = await self.db.upsert_organization(Organization(
                        name=aidev_org.login,
                        url=f"https://github.com/{aidev_org.login}",
                    ))
                    repos = await self._collect_repos_from_aidev(org, aidev_org.login)
                    for repo in repos:
                        await out_q.put(repo)
                    total_repos += len(repos)
                    orgs_processed += 1
                    logger.info(f"  → {len(repos)} repos enviados al pipeline de {aidev_org.login}")
                except Exception as e:
                    logger.error(f"Error procesando owner {aidev_org.login}: {e}")
                    continue
        finally:
            await out_q.put(None)

        logger.info(f"Total repos enviados al pipeline: {total_repos}")
        return {
            "org": f"AIDev-{orgs_processed}-orgs",
            "repos_selected": total_repos,
            "repo_limit": self.config.repo_limit,
            "aidev_orgs_processed": orgs_processed,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _collect_repos_from_aidev(
        self, org: Organization, org_login: str
    ) -> list[Repository]:
        """Obtiene repos del dataset AIDev (en lugar de la GitHub API)."""
        assert self.aidev_client is not None
        assert org.id is not None

        all_repos: list[Repository] = []
        for row in self.aidev_client.iter_repos(
            org_filter=org_login,
            min_stars=self.config.repo_min_stars,
        ):
            if self.config.skip_archived and row.get("archived"):
                continue
            normalized = _normalize_aidev_row(row)
            if normalized is None:
                continue
            all_repos.append(Repository.from_api(normalized, org_id=org.id))

        cutoff = datetime.now(UTC) - timedelta(days=self.config.repo_recent_days)
        recent = [r for r in all_repos if r.last_commit_at and r.last_commit_at >= cutoff]

        if len(recent) >= self.config.repo_limit:
            selected = sorted(recent, key=lambda r: r.stars, reverse=True)[: self.config.repo_limit]
        else:
            recent_names = {r.full_name for r in recent}
            inactive = sorted(
                [r for r in all_repos if r.full_name not in recent_names],
                key=lambda r: r.stars,
                reverse=True,
            )
            selected = (
                sorted(recent, key=lambda r: r.stars, reverse=True)
                + inactive[: self.config.repo_limit - len(recent)]
            )

        logger.info(
            f"AIDev repos para '{org_login}': {len(all_repos)} total | "
            f"con actividad reciente: {len(recent)} | seleccionados: {len(selected)}"
        )

        repos: list[Repository] = []
        for repo in selected:
            repo = await self.db.upsert_repository(repo)
            repos.append(repo)
        return repos

