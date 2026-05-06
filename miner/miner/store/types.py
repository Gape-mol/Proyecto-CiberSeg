from __future__ import annotations

from dataclasses import dataclass


# Defines the collections managed by the JSON store.
@dataclass(frozen=True)
class StoreCollections:
    ORGANIZATIONS: str = "organizations"
    REPOSITORIES: str = "repositories"
    GITLEAKS_SCANS: str = "gitleaks_scans"
    GITLEAKS_FINDINGS: str = "gitleaks_findings"
    SBOM_SCANS: str = "sbom_scans"
    SBOM_COMPONENTS: str = "sbom_components"
    GRYPE_SCANS: str = "grype_scans"
    GRYPE_FINDINGS: str = "grype_findings"
    CODEQL_SCANS: str = "codeql_scans"
    CODEQL_FINDINGS: str = "codeql_findings"
    PIPELINE_RUNS: str = "pipeline_runs"
