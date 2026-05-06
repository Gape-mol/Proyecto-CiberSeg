from __future__ import annotations

from typing import Any

from .utils import now_str


# Provides SBOM component persistence helpers.
class SbomStore:
    # Initializes the SBOM store helpers.
    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    # Saves SBOM components into the store.
    def save_components(
        self,
        scan_id: int,
        repo_id: int,
        components: list[dict[str, Any]],
        append_row: Any,
    ) -> None:
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

        for component in components:
            if not component.get("name"):
                continue
            append_row(
                "sbom_components",
                {
                    "scan_id": scan_id,
                    "repo_id": repo_id,
                    "name": component.get("name", ""),
                    "version": component.get("version"),
                    "purl": component.get("purl"),
                    "ecosystem": ecosystem(component.get("purl")),
                    "license": license_name(component),
                    "component_type": component.get("type"),
                    "created_at": now_str(),
                },
            )
