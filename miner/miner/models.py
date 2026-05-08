from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _parse_dt(value: str | None) -> datetime | None:
    """Parsea fechas ISO 8601 que devuelve GitHub."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Organization:
    name: str
    github_id: int | None = None
    url: str | None = None
    id: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Organization:
        return cls(
            name=data["login"],
            github_id=data.get("id"),
            url=data.get("html_url"),
        )


@dataclass
class Repository:
    org_id: int
    name: str
    full_name: str
    clone_url: str
    default_branch: str = "main"
    description: str | None = None
    language: str | None = None
    visibility: str = "private"
    archived: bool = False
    stars: int = 0
    forks: int = 0
    size_kb: int = 0
    last_commit_sha: str | None = None
    last_commit_at: datetime | None = None
    github_created_at: datetime | None = None
    github_updated_at: datetime | None = None
    miner_status: str = "pending"
    id: int | None = None           # DB id

    @property
    def org_name(self) -> str:
        return self.full_name.split("/")[0]

    @classmethod
    def from_api(cls, data: dict[str, Any], org_id: int) -> Repository:
        return cls(
            org_id=org_id,
            name=data["name"],
            full_name=data["full_name"],
            clone_url=data["clone_url"],
            default_branch=data.get("default_branch", "main"),
            description=data.get("description"),
            language=data.get("language"),
            visibility=data.get("visibility", "private"),
            archived=data.get("archived", False),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            size_kb=data.get("size", 0),
            last_commit_at=_parse_dt(data.get("pushed_at")),
            github_created_at=_parse_dt(data.get("created_at")),
            github_updated_at=_parse_dt(data.get("updated_at")),
        )

    @classmethod
    def from_dataset(cls, row: dict[str, Any], org_id: int) -> Repository:
        """Constructs a Repository from an AIDev HuggingFace dataset row."""
        full_name: str = (row.get("full_name") or "").strip()
        name = full_name.split("/")[-1] if "/" in full_name else full_name
        clone_url = row.get("clone_url") or f"https://github.com/{full_name}.git"
        return cls(
            org_id=org_id,
            name=name,
            full_name=full_name,
            clone_url=clone_url,
            default_branch=row.get("default_branch") or "main",
            description=row.get("description"),
            language=row.get("language"),
            visibility=row.get("visibility") or "public",
            archived=bool(row.get("archived", False)),
            stars=int(row.get("stargazers_count") or row.get("stars") or 0),
            forks=int(row.get("forks_count") or row.get("forks") or 0),
            size_kb=int(row.get("size") or 0),
            last_commit_at=_parse_dt(row.get("pushed_at")),
            github_created_at=_parse_dt(row.get("created_at")),
            github_updated_at=_parse_dt(row.get("updated_at")),
        )
