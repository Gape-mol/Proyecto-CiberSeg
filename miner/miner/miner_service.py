from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .git import GitHubClient
from .models import Organization, Repository
from .store import JsonStore

logger = logging.getLogger(__name__)


# Orchestrates repository collection and persistence.
class GitHubMiner:
    # Initializes the miner service with config and storage.
    def __init__(self, config: Any, db: JsonStore) -> None:
        self.config = config
        self.db = db
        self.client = GitHubClient(config.github_token)

    # Registers the organization and returns selected repositories.
    async def run(self) -> tuple[dict[str, Any], list[Repository]]:
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

    # Collects repositories based on recency and popularity rules.
    async def _collect_repos(self, org: Organization) -> list[Repository]:
        all_repos: list[Repository] = []

        fetch_limit = self.config.repo_limit * 4
        logger.info(
            f"Listando repositorios de '{org.name}'… "
            f"(trayendo hasta {fetch_limit} más recientes, límite final: {self.config.repo_limit})"
        )
        async for repo_data in self.client.list_org_repos(
            org.name, visibility=self.config.visibility, max_results=fetch_limit
        ):
            if self.config.skip_archived and repo_data.get("archived"):
                logger.debug(f"Saltando repo archivado: {repo_data['full_name']}")
                continue
            assert org.id is not None
            all_repos.append(Repository.from_api(repo_data, org_id=org.id))
            n = len(all_repos)
            if n % 25 == 0:
                logger.info(f"  … {n} repos listados hasta ahora")

        seen: dict[str, Repository] = {}
        for r in all_repos:
            seen.setdefault(r.full_name, r)
        all_repos = list(seen.values())

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
            f"Total repos en org: {len(all_repos)} | "
            f"con actividad reciente: {len(recent)} | "
            f"seleccionados: {len(selected)}"
        )

        repos: list[Repository] = []
        for repo in selected:
            repo = await self.db.upsert_repository(repo)
            repos.append(repo)
        return repos
