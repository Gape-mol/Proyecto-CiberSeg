from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .db import Database
from .models import Organization, Repository

logger = logging.getLogger(__name__)

@dataclass
class MinerConfig:
    """Toda la config que necesita el miner, cargada desde env/archivo."""

    github_token: str
    org_name: str
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

    @classmethod
    def from_env(cls) -> MinerConfig:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise OSError(
                "Se requiere GITHUB_TOKEN o GH_TOKEN en el entorno."
            )
        org = os.environ.get("GITHUB_ORG")
        if not org:
            raise OSError("Se requiere GITHUB_ORG en el entorno.")

        return cls(
            github_token=token,
            org_name=org,
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
        )


def _parse_depth(value: str | None) -> int | None:
    if value is None or value.lower() in ("none", "full", ""):
        return None
    return int(value)

class GitHubClient:

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._limiter = asyncio.Semaphore(10)

    async def list_org_repos(
        self,
        org: str,
        visibility: str = "all",
        per_page: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        url: str | None = f"{self.BASE_URL}/orgs/{org}/repos"
        params: dict[str, Any] = {"per_page": per_page, "type": visibility, "sort": "full_name"}

        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            while url:
                response = await self._get_with_retry(client, url, params=params)
                repos = response.json()

                if not isinstance(repos, list):
                    # GitHub devolvió error (e.g. 404 org no encontrada)
                    error = repos.get("message", "Unknown error")
                    raise RuntimeError(f"Error de GitHub API: {error}")

                for repo in repos:
                    if not isinstance(repo, dict):
                        raise RuntimeError("GitHub API devolvió un repo con formato inválido")
                    yield repo

                url = self._next_link(response.headers.get("Link", ""))
                params = {}

    async def get_org(self, org: str) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            r = await self._get_with_retry(client, f"{self.BASE_URL}/orgs/{org}")
            payload = r.json()
            if not isinstance(payload, dict):
                raise RuntimeError("GitHub API devolvió una organización con formato inválido")
            return cast(dict[str, Any], payload)

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

    @staticmethod
    def _next_link(link_header: str) -> str | None:
        """Parsea el header Link de GitHub para obtener la URL de la siguiente página."""
        if not link_header:
            return None
        for part in link_header.split(","):
            url_part, *rel_parts = part.strip().split(";")
            if any('rel="next"' in r for r in rel_parts):
                return url_part.strip().strip("<>")
        return None

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
            logger.info(f"[{repo.full_name}] Actualizando (fetch)…")
            await _git_fetch(dest, timeout)
        else:
            logger.info(f"[{repo.full_name}] Clonando…")
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
    cmd = ["git", "clone", "--quiet"]
    if depth is not None:
        cmd += ["--depth", str(depth)]
    cmd += [url, str(dest)]
    await _run_git(cmd, timeout=timeout)


async def _git_fetch(dest: Path, timeout: int) -> None:
    cmd = ["git", "-C", str(dest), "fetch", "--quiet", "--all", "--prune"]
    await _run_git(cmd, timeout=timeout)


async def _get_head_sha(dest: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(dest), "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip()


async def _run_git(cmd: list[str], timeout: int) -> None:
    safe_cmd = [c if "x-access-token" not in c else "***" for c in cmd]
    logger.debug(f"$ {' '.join(safe_cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # No pedir passwords
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as err:
        proc.kill()
        raise TimeoutError(f"Git timeout después de {timeout}s") from err

    if proc.returncode != 0:
        error_msg = stderr.decode().strip()
        error_msg = error_msg.replace(
            next((c for c in cmd if "x-access-token" in c), ""), "***"
        )
        raise RuntimeError(f"git falló (rc={proc.returncode}): {error_msg}")

class GitHubMiner:

    def __init__(self, config: MinerConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self.client = GitHubClient(config.github_token)

    async def run(self) -> tuple[dict[str, Any], list[Repository]]:
        """Registra la org, selecciona repos y los retorna para el pipeline."""
        logger.info(f"Iniciando mining de organización: {self.config.org_name}")

        org_data = await self.client.get_org(self.config.org_name)
        org = await self.db.upsert_organization(Organization.from_api(org_data))
        logger.info(f"Organización '{org.name}' registrada (id={org.id})")

        repos = await self._collect_repos(org)
        logger.info(
            f"Repos seleccionados: {len(repos)} "
            f"(límite={self.config.repo_limit}, "
            f"actividad últimos {self.config.repo_recent_days} días)"
        )

        summary: dict[str, Any] = {
            "org": org.name,
            "repos_selected": len(repos),
            "repo_limit": self.config.repo_limit,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return summary, repos

    async def _collect_repos(self, org: Organization) -> list[Repository]:
        """Lista todos los repos, filtra por actividad reciente, ordena por estrellas y limita."""
        all_repos: list[Repository] = []

        async for repo_data in self.client.list_org_repos(
            org.name, visibility=self.config.visibility
        ):
            if self.config.skip_archived and repo_data.get("archived"):
                logger.debug(f"Saltando repo archivado: {repo_data['full_name']}")
                continue
            assert org.id is not None
            all_repos.append(Repository.from_api(repo_data, org_id=org.id))

        cutoff = datetime.now(UTC) - timedelta(days=self.config.repo_recent_days)
        recent = [r for r in all_repos if r.last_commit_at and r.last_commit_at >= cutoff]

        if len(recent) >= self.config.repo_limit:
            selected = sorted(recent, key=lambda r: r.stars, reverse=True)[: self.config.repo_limit]
        else:
            # Si no hay suficientes repos recientes, completa con los más populares restantes
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
            f"Total repos en org: {len(all_repos)} | "
            f"con actividad reciente: {len(recent)} | "
            f"seleccionados: {len(selected)}"
        )

        # Upsert solo los repos seleccionados
        repos: list[Repository] = []
        for repo in selected:
            repo = await self.db.upsert_repository(repo)
            repos.append(repo)
        return repos
