from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import Organization, Repository
from .codeql_store import CodeqlStore
from .core import StoreCore
from .grype_store import GrypeStore
from .repo_store import RepoStore
from .sbom_store import SbomStore
from .scan_store import ScanStore
from .types import StoreCollections


# Orchestrates specialized stores and exposes the public API.
class JsonStore:
    # Initializes the JSON store orchestrator.
    def __init__(self, db_path: str) -> None:
        self._collections = StoreCollections()
        self._core = StoreCore(db_path, self._collections)
        self._repo_store = RepoStore(self._core.store())
        self._scan_store = ScanStore(self._core.store())
        self._sbom_store = SbomStore(self._core.store())
        self._grype_store = GrypeStore(self._core.store())
        self._codeql_store = CodeqlStore(self._core.store())

    # Loads or creates the JSON store on disk.
    async def connect(self) -> None:
        await self._core.connect()

    # Flushes the store to disk and releases resources.
    async def close(self) -> None:
        await self._core.close()

    # Keeps compatibility with legacy schema calls.
    async def apply_schema(self, schema_path: Path) -> None:
        await self._core.apply_schema(schema_path)

    # Creates or updates an organization record.
    async def upsert_organization(self, org: Organization) -> Organization:
        async with self._core.lock():
            org = self._repo_store.upsert_organization(
                org,
                allocator=self._core.allocate_id_unlocked,
                finder=self._core.find_one_unlocked,
            )
            self._core.flush_unlocked()
            return org

    # Creates or updates a repository record.
    async def upsert_repository(self, repo: Repository) -> Repository:
        async with self._core.lock():
            repo = self._repo_store.upsert_repository(
                repo,
                allocator=self._core.allocate_id_unlocked,
                finder=self._core.find_one_unlocked,
            )
            self._core.flush_unlocked()
            return repo

    # Updates the miner status for a repository record.
    async def update_repo_status(self, repo_id: int, status: str, error: str | None = None) -> None:
        async with self._core.lock():
            self._repo_store.update_repo_status(
                repo_id,
                status,
                error,
                finder=self._core.find_one_unlocked,
            )
            self._core.flush_unlocked()

    # Marks a repository as cloned and stores its metadata.
    async def mark_repo_cloned(self, repo_id: int, clone_path: str, commit_sha: str | None) -> None:
        async with self._core.lock():
            self._repo_store.mark_repo_cloned(
                repo_id,
                clone_path,
                commit_sha,
                finder=self._core.find_one_unlocked,
            )
            self._core.flush_unlocked()

    # Fetches a repository record by id.
    async def get_repo_by_id(self, repo_id: int) -> Repository:
        async with self._core.lock():
            return self._repo_store.get_repo_by_id(
                repo_id,
                finder=self._core.find_one_unlocked,
            )

    # Saves a gitleaks scan summary and returns its id.
    async def save_gitleaks_scan(
        self,
        repo_id: int,
        commit_sha: str | None,
        report_path: str | None,
        findings_count: int,
    ) -> int:
        async with self._core.lock():
            scan_id = self._scan_store.add_scan(
                self._collections.GITLEAKS_SCANS,
                repo_id,
                self._core.append_row_unlocked,
                commit_sha=commit_sha,
                report_path=report_path,
                findings_count=findings_count,
            )
            self._core.flush_unlocked()
            return scan_id

    # Saves an SBOM scan summary and returns its id.
    async def save_sbom_scan(self, repo_id: int, sbom_path: str | None, component_count: int) -> int:
        async with self._core.lock():
            scan_id = self._scan_store.add_scan(
                self._collections.SBOM_SCANS,
                repo_id,
                self._core.append_row_unlocked,
                tool="syft",
                sbom_format="cyclonedx-json",
                sbom_path=sbom_path,
                component_count=component_count,
            )
            self._core.flush_unlocked()
            return scan_id

    # Saves a grype scan summary and returns its id.
    async def save_grype_scan(self, repo_id: int, report_path: str | None, findings_count: int) -> int:
        async with self._core.lock():
            scan_id = self._scan_store.add_scan(
                self._collections.GRYPE_SCANS,
                repo_id,
                self._core.append_row_unlocked,
                sbom_scan_id=None,
                report_path=report_path,
                findings_count=findings_count,
            )
            self._core.flush_unlocked()
            return scan_id

    # Saves a codeql scan summary and returns its id.
    async def save_codeql_scan(
        self,
        repo_id: int,
        language: str | None,
        report_path: str | None,
        findings_count: int,
    ) -> int:
        async with self._core.lock():
            scan_id = self._scan_store.add_scan(
                self._collections.CODEQL_SCANS,
                repo_id,
                self._core.append_row_unlocked,
                language=language,
                report_path=report_path,
                findings_count=findings_count,
            )
            self._core.flush_unlocked()
            return scan_id

    # Persists gitleaks findings into the JSON store.
    async def save_gitleaks_findings(
        self,
        scan_id: int,
        repo_id: int,
        findings: list[dict[str, Any]],
    ) -> None:
        if not findings:
            return
        async with self._core.lock():
            self._scan_store.save_gitleaks_findings(
                scan_id,
                repo_id,
                findings,
                self._core.append_row_unlocked,
            )
            self._core.flush_unlocked()

    # Persists SBOM components into the JSON store.
    async def save_sbom_components(
        self,
        scan_id: int,
        repo_id: int,
        components: list[dict[str, Any]],
    ) -> None:
        if not components:
            return
        async with self._core.lock():
            self._sbom_store.save_components(
                scan_id,
                repo_id,
                components,
                self._core.append_row_unlocked,
            )
            self._core.flush_unlocked()

    # Persists grype findings into the JSON store.
    async def save_grype_findings(
        self,
        scan_id: int,
        repo_id: int,
        matches: list[dict[str, Any]],
    ) -> None:
        if not matches:
            return
        async with self._core.lock():
            self._grype_store.save_findings(
                scan_id,
                repo_id,
                matches,
                self._core.append_row_unlocked,
                grype_locations=self._grype_locations,
            )
            self._core.flush_unlocked()

    # Persists codeql findings into the JSON store.
    async def save_codeql_findings(
        self,
        scan_id: int,
        repo_id: int,
        results: list[dict[str, Any]],
        rules_by_id: dict[str, dict[str, Any]],
    ) -> None:
        if not results:
            return
        async with self._core.lock():
            self._codeql_store.save_findings(
                scan_id,
                repo_id,
                results,
                rules_by_id,
                self._core.append_row_unlocked,
            )
            self._core.flush_unlocked()

    # Returns a list of repositories that finished cloning.
    async def get_cloned_repos(self) -> list[dict[str, Any]]:
        async with self._core.lock():
            return self._repo_store.get_cloned_repos()

    def _grype_locations(self, match: dict[str, Any]) -> tuple[str | None, list[str]]:
        artifact = match.get("artifact", {})
        if not isinstance(artifact, dict):
            return None, []

        locations: list[str] = []
        for entry in artifact.get("locations", []):
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if isinstance(path, str) and path:
                locations.append(path)

        if locations:
            return locations[0], locations

        name = artifact.get("name")
        version = artifact.get("version")
        package_type = artifact.get("type")
        if isinstance(name, str) and name:
            suffix = f"@{version}" if isinstance(version, str) and version else ""
            prefix = f"{package_type}:" if isinstance(package_type, str) and package_type else ""
            fallback = f"{prefix}{name}{suffix}"
            return fallback, [fallback]

        return None, []
