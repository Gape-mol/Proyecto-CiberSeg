from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..models import Repository

logger = logging.getLogger(__name__)


# Holds clone results for repositories.
@dataclass
class CloneResult:
    repo_full_name: str
    success: bool
    clone_path: Path | None = None
    commit_sha: str | None = None
    error: str | None = None


# Clones or updates a repository and returns a CloneResult.
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


# Adds token authentication to a clone URL.
def _auth_clone_url(clone_url: str, token: str) -> str:
    return clone_url.replace("https://", f"https://x-access-token:{token}@")


# Runs git clone for a repository.
async def _git_clone(url: str, dest: Path, depth: int | None, timeout: int) -> None:
    cmd = ["git", "clone"]
    if depth is not None:
        cmd += ["--depth", str(depth)]
    cmd += [url, str(dest)]
    await _run_git(cmd, timeout=timeout, stream_progress=False)


# Runs git fetch to update a repository.
async def _git_fetch(dest: Path, timeout: int) -> None:
    cmd = ["git", "-C", str(dest), "fetch", "--quiet", "--all", "--prune"]
    await _run_git(cmd, timeout=timeout, stream_progress=False)


# Retrieves the current HEAD commit SHA.
async def _get_head_sha(dest: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(dest),
        "rev-parse",
        "HEAD",
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


# Executes git commands with optional progress streaming.
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
        raise TimeoutError(f"Git timeout despues de {timeout}s") from err

    if proc.returncode != 0:
        stderr_str = b"".join(stderr_chunks).decode(errors="replace").strip()
        stderr_str = stderr_str.replace(
            next((c for c in cmd if "x-access-token" in c), ""), "***"
        )
        raise RuntimeError(f"git fallo (rc={proc.returncode}): {stderr_str}")
