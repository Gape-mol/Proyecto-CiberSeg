from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# Holds configuration values for the miner runtime.
@dataclass
class MinerConfig:
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

    # Builds MinerConfig from environment variables.
    @classmethod
    def from_env(cls) -> MinerConfig:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise OSError("Se requiere GITHUB_TOKEN o GH_TOKEN en el entorno.")
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


# Parses the clone depth value from environment variables.
def _parse_depth(value: str | None) -> int | None:
    if value is None or value.lower() in ("none", "full", ""):
        return None
    return int(value)
