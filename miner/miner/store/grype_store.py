from __future__ import annotations

from typing import Any

from .utils import now_str


# Provides Grype findings persistence helpers.
class GrypeStore:
    # Initializes the Grype store helpers.
    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    # Saves Grype findings into the store.
    def save_findings(
        self,
        scan_id: int,
        repo_id: int,
        matches: list[dict[str, Any]],
        append_row: Any,
        grype_locations: Any,
    ) -> None:
        for match in matches:
            vuln = match.get("vulnerability", {})
            artifact = match.get("artifact", {})
            if not isinstance(vuln, dict) or not isinstance(artifact, dict):
                continue
            primary_location, all_locations = grype_locations(match)

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

            severity = vuln.get("severity") or ""
            if not severity or severity.lower() == "unknown":
                for rv in related:
                    if isinstance(rv, dict):
                        rv_sev = rv.get("severity") or ""
                        if rv_sev and rv_sev.lower() != "unknown":
                            severity = rv_sev
                            break

            append_row(
                "grype_findings",
                {
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
                    "created_at": now_str(),
                },
            )
