from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import Organization, Repository
from .utils import dt_str, parse_dt, now_str


# Provides organization and repository persistence helpers.
class RepoStore:
    # Initializes the repository store helpers.
    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    # Creates a Repository object from a stored record.
    def repo_from_record(self, record: dict[str, Any]) -> Repository:
        return Repository(
            id=record["id"],
            org_id=record["org_id"],
            name=record["name"],
            full_name=record["full_name"],
            clone_url=record["clone_url"],
            default_branch=record.get("default_branch", "main"),
            description=record.get("description"),
            language=record.get("language"),
            visibility=record.get("visibility", "private"),
            archived=bool(record.get("archived", False)),
            stars=record.get("stars", 0),
            forks=record.get("forks", 0),
            size_kb=record.get("size_kb", 0),
            last_commit_sha=record.get("last_commit_sha"),
            last_commit_at=parse_dt(record.get("last_commit_at")),
            github_created_at=parse_dt(record.get("github_created_at")),
            github_updated_at=parse_dt(record.get("github_updated_at")),
            miner_status=record.get("miner_status", "pending"),
        )

    # Inserts or updates an organization record.
    def upsert_organization(self, org: Organization, allocator: Any, finder: Any) -> Organization:
        row = finder("organizations", name=org.name)
        if row is None:
            row = {
                "id": allocator("organizations"),
                "name": org.name,
                "github_id": org.github_id,
                "url": org.url,
                "fetched_at": now_str(),
            }
            self._store["organizations"].append(row)
        else:
            row.update(
                {
                    "github_id": org.github_id,
                    "url": org.url,
                    "fetched_at": now_str(),
                }
            )
        org.id = row["id"]
        return org

    # Inserts or updates a repository record.
    def upsert_repository(self, repo: Repository, allocator: Any, finder: Any) -> Repository:
        row = finder("repositories", full_name=repo.full_name)
        if row is None:
            row = {
                "id": allocator("repositories"),
                "org_id": repo.org_id,
                "name": repo.name,
                "full_name": repo.full_name,
                "clone_url": repo.clone_url,
                "description": repo.description,
                "default_branch": repo.default_branch,
                "language": repo.language,
                "visibility": repo.visibility,
                "archived": repo.archived,
                "stars": repo.stars,
                "forks": repo.forks,
                "size_kb": repo.size_kb,
                "clone_path": None,
                "cloned_at": None,
                "last_commit_sha": repo.last_commit_sha,
                "last_commit_at": dt_str(repo.last_commit_at),
                "github_created_at": dt_str(repo.github_created_at),
                "github_updated_at": dt_str(repo.github_updated_at),
                "miner_status": "pending",
                "miner_error": None,
                "created_at": now_str(),
                "updated_at": now_str(),
            }
            self._store["repositories"].append(row)
        else:
            row.update(
                {
                    "org_id": repo.org_id,
                    "name": repo.name,
                    "clone_url": repo.clone_url,
                    "description": repo.description,
                    "default_branch": repo.default_branch,
                    "language": repo.language,
                    "visibility": repo.visibility,
                    "archived": repo.archived,
                    "stars": repo.stars,
                    "forks": repo.forks,
                    "size_kb": repo.size_kb,
                    "last_commit_at": dt_str(repo.last_commit_at),
                    "github_created_at": dt_str(repo.github_created_at),
                    "github_updated_at": dt_str(repo.github_updated_at),
                    "updated_at": now_str(),
                }
            )
        repo.id = row["id"]
        repo.miner_status = row["miner_status"]
        return repo

    # Updates the miner status for a repository record.
    def update_repo_status(self, repo_id: int, status: str, error: str | None, finder: Any) -> None:
        row = finder("repositories", id=repo_id)
        if row is None:
            raise ValueError(f"Repo id={repo_id} no encontrado en store")
        row["miner_status"] = status
        row["miner_error"] = error
        row["updated_at"] = now_str()

    # Marks a repository as cloned and stores its metadata.
    def mark_repo_cloned(self, repo_id: int, clone_path: str, commit_sha: str | None, finder: Any) -> None:
        row = finder("repositories", id=repo_id)
        if row is None:
            raise ValueError(f"Repo id={repo_id} no encontrado en store")
        row.update(
            {
                "miner_status": "cloned",
                "clone_path": clone_path,
                "last_commit_sha": commit_sha,
                "cloned_at": now_str(),
                "miner_error": None,
                "updated_at": now_str(),
            }
        )

    # Returns a repository record by id as a Repository object.
    def get_repo_by_id(self, repo_id: int, finder: Any) -> Repository:
        row = finder("repositories", id=repo_id)
        if row is None:
            raise ValueError(f"Repo id={repo_id} no encontrado en store")
        return self.repo_from_record(deepcopy(row))

    # Returns repositories that finished cloning.
    def get_cloned_repos(self) -> list[dict[str, Any]]:
        orgs_by_id = {
            org["id"]: org["name"] for org in self._store["organizations"]
        }
        rows = []
        for repo in self._store["repositories"]:
            if repo.get("miner_status") != "cloned":
                continue
            rows.append(
                {
                    "id": repo["id"],
                    "full_name": repo["full_name"],
                    "name": repo["name"],
                    "clone_path": repo.get("clone_path"),
                    "language": repo.get("language"),
                    "last_commit_sha": repo.get("last_commit_sha"),
                    "default_branch": repo.get("default_branch"),
                    "org_name": orgs_by_id.get(repo["org_id"], repo["full_name"].split("/")[0]),
                }
            )
        return sorted(rows, key=lambda row: row["full_name"])
