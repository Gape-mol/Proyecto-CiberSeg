from __future__ import annotations

import asyncio
from pathlib import Path

from ..git import clone_or_update_repo
from ..models import Repository
from .types import StageResult, repo_id


# Clones or updates a repository and returns a stage result.
async def stage_clone(
    repo: Repository,
    clone_root: Path,
    token: str,
    depth: int | None,
    timeout: int,
) -> StageResult:
    repo_id_value = repo_id(repo)
    t0 = asyncio.get_event_loop().time()
    result = await clone_or_update_repo(
        repo=repo,
        clone_root=clone_root,
        token=token,
        depth=depth,
        timeout=timeout,
    )
    duration = asyncio.get_event_loop().time() - t0

    return StageResult(
        repo_id=repo_id_value,
        repo_full_name=repo.full_name,
        stage="clone",
        success=result.success,
        duration_s=duration,
        error=result.error,
        metadata={
            "clone_path": str(result.clone_path) if result.clone_path else None,
            "commit_sha": result.commit_sha,
        },
    )
