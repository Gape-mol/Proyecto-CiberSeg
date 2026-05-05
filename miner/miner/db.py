from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .models import Organization, Repository

logger = logging.getLogger(__name__)

_COLLECTIONS = [
    "organizations",
    "repositories",
    "gitleaks_scans",
    "gitleaks_findings",
    "sbom_scans",
    "sbom_components",
    "grype_scans",
    "grype_findings",
    "codeql_scans",
    "codeql_findings",
    "pipeline_runs",
]


def _now_str() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso(value: str | None) -> str | None:
    dt = _parse_dt(value)
    return dt.isoformat() if dt else None


def _dt_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _file_location(file_path: str | None, line: Any = None) -> str | None:
    if not file_path:
        return None
    if isinstance(line, int):
        return f"{file_path}:{line}"
    return file_path


def _grype_locations(match: dict[str, Any]) -> tuple[str | None, list[str]]:
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


def _base_store() -> dict[str, Any]:
    return {
        "meta": {
            "format": "miner-json-v1",
            "updated_at": _now_str(),
        },
        "next_ids": {name: 1 for name in _COLLECTIONS},
        **{name: [] for name in _COLLECTIONS},
    }


def _repo_from_record(record: dict[str, Any]) -> Repository:
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
        last_commit_at=_parse_dt(record.get("last_commit_at")),
        github_created_at=_parse_dt(record.get("github_created_at")),
        github_updated_at=_parse_dt(record.get("github_updated_at")),
        miner_status=record.get("miner_status", "pending"),
    )


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._store: dict[str, Any] = _base_store()

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if self._db_path.exists() and self._db_path.stat().st_size > 0:
            self._store = self._load_store()
        else:
            self._store = _base_store()
            self._flush_unlocked()
        logger.info(f"JSON store conectado: {self._db_path}")

    async def close(self) -> None:
        async with self._lock:
            self._flush_unlocked()
        logger.info("JSON store cerrado.")

    async def apply_schema(self, schema_path: Path) -> None:
        # Compatibilidad con el flujo anterior: ya no hay schema que aplicar.
        logger.info(f"Schema SQLite ignorado; usando JSON store en {self._db_path}")

    def _load_store(self) -> dict[str, Any]:
        data = cast(dict[str, Any], json.loads(self._db_path.read_text()))
        for name in _COLLECTIONS:
            data.setdefault(name, [])
        next_ids = data.setdefault("next_ids", {})
        for name in _COLLECTIONS:
            next_ids.setdefault(name, self._next_id_from_rows(data[name]))
        data.setdefault("meta", {})
        data["meta"].setdefault("format", "miner-json-v1")
        data["meta"]["updated_at"] = _now_str()
        return data

    @staticmethod
    def _next_id_from_rows(rows: list[dict[str, Any]]) -> int:
        return max((row.get("id", 0) for row in rows), default=0) + 1

    def _flush_unlocked(self) -> None:
        self._store["meta"]["updated_at"] = _now_str()
        self._db_path.write_text(json.dumps(self._store, indent=2, ensure_ascii=True))

    def _allocate_id_unlocked(self, collection: str) -> int:
        next_id = cast(int, self._store["next_ids"][collection])
        self._store["next_ids"][collection] += 1
        return next_id

    def _find_one_unlocked(self, collection: str, **filters: Any) -> dict[str, Any] | None:
        for row in self._store[collection]:
            if all(row.get(key) == value for key, value in filters.items()):
                return cast(dict[str, Any], row)
        return None

    async def upsert_organization(self, org: Organization) -> Organization:
        async with self._lock:
            row = self._find_one_unlocked("organizations", name=org.name)
            if row is None:
                row = {
                    "id": self._allocate_id_unlocked("organizations"),
                    "name": org.name,
                    "github_id": org.github_id,
                    "url": org.url,
                    "fetched_at": _now_str(),
                }
                self._store["organizations"].append(row)
            else:
                row.update(
                    {
                        "github_id": org.github_id,
                        "url": org.url,
                        "fetched_at": _now_str(),
                    }
                )
            self._flush_unlocked()
            org.id = row["id"]
            return org

    async def upsert_repository(self, repo: Repository) -> Repository:
        async with self._lock:
            row = self._find_one_unlocked("repositories", full_name=repo.full_name)
            if row is None:
                row = {
                    "id": self._allocate_id_unlocked("repositories"),
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
                    "last_commit_at": _dt_str(repo.last_commit_at),
                    "github_created_at": _dt_str(repo.github_created_at),
                    "github_updated_at": _dt_str(repo.github_updated_at),
                    "miner_status": "pending",
                    "miner_error": None,
                    "created_at": _now_str(),
                    "updated_at": _now_str(),
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
                        "last_commit_at": _dt_str(repo.last_commit_at),
                        "github_created_at": _dt_str(repo.github_created_at),
                        "github_updated_at": _dt_str(repo.github_updated_at),
                        "updated_at": _now_str(),
                    }
                )
            self._flush_unlocked()
            repo.id = row["id"]
            repo.miner_status = row["miner_status"]
            return repo

    async def update_repo_status(
        self,
        repo_id: int,
        status: str,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            row = self._find_one_unlocked("repositories", id=repo_id)
            if row is None:
                raise ValueError(f"Repo id={repo_id} no encontrado en store")
            row["miner_status"] = status
            row["miner_error"] = error
            row["updated_at"] = _now_str()
            self._flush_unlocked()

    async def mark_repo_cloned(
        self,
        repo_id: int,
        clone_path: str,
        commit_sha: str | None,
    ) -> None:
        async with self._lock:
            row = self._find_one_unlocked("repositories", id=repo_id)
            if row is None:
                raise ValueError(f"Repo id={repo_id} no encontrado en store")
            row.update(
                {
                    "miner_status": "cloned",
                    "clone_path": clone_path,
                    "last_commit_sha": commit_sha,
                    "cloned_at": _now_str(),
                    "miner_error": None,
                    "updated_at": _now_str(),
                }
            )
            self._flush_unlocked()

    async def get_repo_by_id(self, repo_id: int) -> Repository:
        async with self._lock:
            row = self._find_one_unlocked("repositories", id=repo_id)
            if row is None:
                raise ValueError(f"Repo id={repo_id} no encontrado en store")
            return _repo_from_record(deepcopy(row))

    async def save_gitleaks_scan(
        self,
        repo_id: int,
        commit_sha: str | None,
        report_path: str | None,
        findings_count: int,
    ) -> int:
        async with self._lock:
            scan_id = self._allocate_id_unlocked("gitleaks_scans")
            self._store["gitleaks_scans"].append(
                {
                    "id": scan_id,
                    "repo_id": repo_id,
                    "scanned_at": _now_str(),
                    "status": "done",
                    "error": None,
                    "commit_sha": commit_sha,
                    "report_path": report_path,
                    "findings_count": findings_count,
                }
            )
            self._flush_unlocked()
            return scan_id

    async def save_sbom_scan(
        self,
        repo_id: int,
        sbom_path: str | None,
        component_count: int,
    ) -> int:
        async with self._lock:
            scan_id = self._allocate_id_unlocked("sbom_scans")
            self._store["sbom_scans"].append(
                {
                    "id": scan_id,
                    "repo_id": repo_id,
                    "scanned_at": _now_str(),
                    "status": "done",
                    "error": None,
                    "tool": "syft",
                    "sbom_format": "cyclonedx-json",
                    "sbom_path": sbom_path,
                    "component_count": component_count,
                }
            )
            self._flush_unlocked()
            return scan_id

    async def save_grype_scan(
        self,
        repo_id: int,
        report_path: str | None,
        findings_count: int,
    ) -> int:
        async with self._lock:
            scan_id = self._allocate_id_unlocked("grype_scans")
            self._store["grype_scans"].append(
                {
                    "id": scan_id,
                    "repo_id": repo_id,
                    "sbom_scan_id": None,
                    "scanned_at": _now_str(),
                    "status": "done",
                    "error": None,
                    "report_path": report_path,
                    "findings_count": findings_count,
                }
            )
            self._flush_unlocked()
            return scan_id

    async def save_codeql_scan(
        self,
        repo_id: int,
        language: str | None,
        report_path: str | None,
        findings_count: int,
    ) -> int:
        async with self._lock:
            scan_id = self._allocate_id_unlocked("codeql_scans")
            self._store["codeql_scans"].append(
                {
                    "id": scan_id,
                    "repo_id": repo_id,
                    "scanned_at": _now_str(),
                    "status": "done",
                    "error": None,
                    "language": language,
                    "report_path": report_path,
                    "findings_count": findings_count,
                }
            )
            self._flush_unlocked()
            return scan_id

    async def save_gitleaks_findings(
        self,
        scan_id: int,
        repo_id: int,
        findings: list[dict[str, Any]],
    ) -> None:
        if not findings:
            return
        async with self._lock:
            for finding in findings:
                self._store["gitleaks_findings"].append(
                    {
                        "id": self._allocate_id_unlocked("gitleaks_findings"),
                        "scan_id": scan_id,
                        "repo_id": repo_id,
                        "rule_id": finding.get("RuleID"),
                        "description": finding.get("Description"),
                        "severity": finding.get("Severity"),
                        "file_path": finding.get("File"),
                        "location": _file_location(
                            finding.get("File"),
                            finding.get("StartLine"),
                        ),
                        "line_start": finding.get("StartLine"),
                        "line_end": finding.get("EndLine"),
                        "commit": finding.get("Commit"),
                        "author": finding.get("Author"),
                        "author_email": finding.get("Email"),
                        "date": _parse_iso(finding.get("Date")),
                        "secret_fingerprint": finding.get("Fingerprint"),
                        "raw_match": finding.get("Match"),
                        "created_at": _now_str(),
                    }
                )
            self._flush_unlocked()

    async def save_sbom_components(
        self,
        scan_id: int,
        repo_id: int,
        components: list[dict[str, Any]],
    ) -> None:
        if not components:
            return

        def ecosystem(purl: str | None) -> str | None:
            if not purl:
                return None
            try:
                return purl.split(":")[1].split("/")[0]
            except IndexError:
                return None

        def license_name(component: dict[str, Any]) -> str | None:
            for entry in component.get("licenses", []):
                if not isinstance(entry, dict):
                    continue
                license_info = entry.get("license", {})
                if not isinstance(license_info, dict):
                    continue
                return license_info.get("id") or license_info.get("name")
            return None

        async with self._lock:
            for component in components:
                if not component.get("name"):
                    continue
                self._store["sbom_components"].append(
                    {
                        "id": self._allocate_id_unlocked("sbom_components"),
                        "scan_id": scan_id,
                        "repo_id": repo_id,
                        "name": component.get("name", ""),
                        "version": component.get("version"),
                        "purl": component.get("purl"),
                        "ecosystem": ecosystem(component.get("purl")),
                        "license": license_name(component),
                        "component_type": component.get("type"),
                        "created_at": _now_str(),
                    }
                )
            self._flush_unlocked()

    async def save_grype_findings(
        self,
        scan_id: int,
        repo_id: int,
        matches: list[dict[str, Any]],
    ) -> None:
        if not matches:
            return
        async with self._lock:
            for match in matches:
                vuln = match.get("vulnerability", {})
                artifact = match.get("artifact", {})
                if not isinstance(vuln, dict) or not isinstance(artifact, dict):
                    continue
                primary_location, all_locations = _grype_locations(match)

                # vulnerability.cvss suele estar vacío en entradas de namespace
                # específico (ej. github:language:*). El score NVD real está en
                # relatedVulnerabilities[].cvss — lo buscamos como fallback.
                related = match.get("relatedVulnerabilities") or []
                cvss_sources: list[list[Any]] = [
                    vuln.get("cvss") or [],
                    *[rv.get("cvss") or [] for rv in related if isinstance(rv, dict)],
                ]
                cvss_score = None
                for cvss_list in cvss_sources:
                    for cvss in cvss_list:
                        if not isinstance(cvss, dict):
                            continue
                        score = cvss.get("metrics", {}).get("baseScore")
                        if score is not None:
                            cvss_score = float(score)
                            break
                    if cvss_score is not None:
                        break

                # severity también puede venir vacía en advisories propios;
                # si es así, usar la del entry NVD relacionado.
                severity = vuln.get("severity") or ""
                if not severity or severity.lower() == "unknown":
                    for rv in related:
                        if isinstance(rv, dict):
                            rv_sev = rv.get("severity") or ""
                            if rv_sev and rv_sev.lower() != "unknown":
                                severity = rv_sev
                                break

                self._store["grype_findings"].append(
                    {
                        "id": self._allocate_id_unlocked("grype_findings"),
                        "scan_id": scan_id,
                        "repo_id": repo_id,
                        "vulnerability_id": vuln.get("id"),
                        "severity": severity or vuln.get("severity"),
                        "location": primary_location,
                        "locations": all_locations,
                        "cvss_score": cvss_score,
                        "package_name": artifact.get("name"),
                        "package_version": artifact.get("version"),
                        "package_type": artifact.get("type"),
                        "fix_versions": vuln.get("fix", {}).get("versions") or [],
                        "description": vuln.get("description"),
                        "urls": vuln.get("urls") or [],
                        "created_at": _now_str(),
                    }
                )
            self._flush_unlocked()

    async def save_codeql_findings(
        self,
        scan_id: int,
        repo_id: int,
        results: list[dict[str, Any]],
        rules_by_id: dict[str, dict[str, Any]],
    ) -> None:
        if not results:
            return

        level_to_severity = {
            "error": "high", "warning": "medium", "note": "low",
            "recommendation": "low",
        }

        async with self._lock:
            for result in results:
                rule_id = result.get("ruleId", "")
                rule = rules_by_id.get(rule_id, {})
                props = rule.get("properties", {})
                if not isinstance(props, dict):
                    props = {}
                level = result.get("level", "")
                rule_sev = props.get("problem.severity", "")
                # Normalizar siempre a high/medium/low: intentar level primero,
                # luego problem.severity del rule (también puede ser "error"/"warning")
                severity = (
                    level_to_severity.get(level)
                    or level_to_severity.get((rule_sev or "").lower())
                    or (rule_sev.lower() if rule_sev else None)
                    or "medium"
                )
                locations = result.get("locations", [{}])
                if not isinstance(locations, list):
                    locations = [{}]
                physical = locations[0].get("physicalLocation", {}) if locations else {}
                if not isinstance(physical, dict):
                    physical = {}
                region = physical.get("region", {})
                if not isinstance(region, dict):
                    region = {}
                self._store["codeql_findings"].append(
                    {
                        "id": self._allocate_id_unlocked("codeql_findings"),
                        "scan_id": scan_id,
                        "repo_id": repo_id,
                        "rule_id": rule_id,
                        "rule_name": rule.get("name"),
                        "severity": severity,
                        "kind": level,
                        "message": result.get("message", {}).get("text"),
                        "file_path": physical.get("artifactLocation", {}).get("uri"),
                        "location": _file_location(
                            physical.get("artifactLocation", {}).get("uri"),
                            region.get("startLine"),
                        ),
                        "start_line": region.get("startLine"),
                        "start_column": region.get("startColumn"),
                        "end_line": region.get("endLine"),
                        "end_column": region.get("endColumn"),
                        "cwe": [
                            tag
                            for tag in props.get("tags", [])
                            if tag.startswith("external/cwe")
                        ],
                        "tags": props.get("tags", []),
                        "created_at": _now_str(),
                    }
                )
            self._flush_unlocked()

    async def get_cloned_repos(self) -> list[dict[str, Any]]:
        async with self._lock:
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
