from __future__ import annotations

"""Compatibility module: re-exports miner components after refactor."""

from .config import MinerConfig
from .git import GitHubClient, CloneResult, clone_or_update_repo
from .miner_service import GitHubMiner

__all__ = [
    "MinerConfig",
    "GitHubClient",
    "CloneResult",
    "clone_or_update_repo",
    "GitHubMiner",
]
