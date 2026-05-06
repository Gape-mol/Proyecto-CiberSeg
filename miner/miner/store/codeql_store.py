from __future__ import annotations

from typing import Any

from .utils import file_location, now_str


# Provides CodeQL findings persistence helpers.
class CodeqlStore:
    # Initializes the CodeQL store helpers.
    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    # Saves CodeQL findings into the store.
    def save_findings(
        self,
        scan_id: int,
        repo_id: int,
        results: list[dict[str, Any]],
        rules_by_id: dict[str, dict[str, Any]],
        append_row: Any,
    ) -> None:
        level_to_severity = {
            "error": "high", "warning": "medium", "note": "low",
            "recommendation": "low",
        }

        for result in results:
            rule_id = result.get("ruleId", "")
            rule = rules_by_id.get(rule_id, {})
            props = rule.get("properties", {})
            if not isinstance(props, dict):
                props = {}
            level = result.get("level", "")
            rule_sev = props.get("problem.severity", "")
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
            append_row(
                "codeql_findings",
                {
                    "scan_id": scan_id,
                    "repo_id": repo_id,
                    "rule_id": rule_id,
                    "rule_name": rule.get("name"),
                    "severity": severity,
                    "kind": level,
                    "message": result.get("message", {}).get("text"),
                    "file_path": physical.get("artifactLocation", {}).get("uri"),
                    "location": file_location(
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
                    "created_at": now_str(),
                },
            )
