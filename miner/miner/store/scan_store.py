from __future__ import annotations

from typing import Any

from .utils import now_str, parse_iso, file_location


# Provides scan and findings persistence helpers.
class ScanStore:
    # Initializes the scan store helpers.
    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    # Adds a scan record with standard fields and returns its id.
    def add_scan(self, collection: str, repo_id: int, append_row: Any, **extra_fields: Any) -> int:
        row = {
            "repo_id": repo_id,
            "scanned_at": now_str(),
            "status": "done",
            "error": None,
        }
        row.update(extra_fields)
        return append_row(collection, row)

    # Saves gitleaks findings into the store.
    def save_gitleaks_findings(
        self,
        scan_id: int,
        repo_id: int,
        findings: list[dict[str, Any]],
        append_row: Any,
    ) -> None:
        for finding in findings:
            append_row(
                "gitleaks_findings",
                {
                    "scan_id": scan_id,
                    "repo_id": repo_id,
                    "rule_id": finding.get("RuleID"),
                    "description": finding.get("Description"),
                    "severity": finding.get("Severity"),
                    "file_path": finding.get("File"),
                    "location": file_location(
                        finding.get("File"),
                        finding.get("StartLine"),
                    ),
                    "line_start": finding.get("StartLine"),
                    "line_end": finding.get("EndLine"),
                    "commit": finding.get("Commit"),
                    "author": finding.get("Author"),
                    "author_email": finding.get("Email"),
                    "date": parse_iso(finding.get("Date")),
                    "secret_fingerprint": finding.get("Fingerprint"),
                    "raw_match": finding.get("Match"),
                    "created_at": now_str(),
                },
            )
