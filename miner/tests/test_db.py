from __future__ import annotations

import json
from datetime import UTC, datetime

from miner.db import Database
from miner.models import Organization, Repository


async def test_json_store_persists_repositories_and_findings(tmp_path):
    db_path = tmp_path / "secpipeline.json"
    db = Database(str(db_path))
    await db.connect()

    org = await db.upsert_organization(
        Organization(name="test-org", github_id=123, url="https://github.com/test-org")
    )
    assert org.id is not None
    repo = await db.upsert_repository(
        Repository(
            org_id=org.id,
            name="repo-a",
            full_name="test-org/repo-a",
            clone_url="https://github.com/test-org/repo-a.git",
            language="Python",
            last_commit_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
    )
    assert repo.id is not None

    await db.update_repo_status(repo.id, "cloning")
    await db.mark_repo_cloned(repo.id, "/data/repos/test-org/repo-a", "abc123")

    gitleaks_scan_id = await db.save_gitleaks_scan(repo.id, "abc123", "/tmp/gitleaks.json", 1)
    await db.save_gitleaks_findings(
        gitleaks_scan_id,
        repo.id,
        [
            {
                "RuleID": "github-pat",
                "Description": "Hardcoded token",
                "Severity": "high",
                "File": "app.py",
                "StartLine": 10,
                "EndLine": 10,
                "Commit": "abc123",
                "Date": "2024-01-01T00:00:00Z",
            }
        ],
    )

    sbom_scan_id = await db.save_sbom_scan(repo.id, "/tmp/sbom.json", 1)
    await db.save_sbom_components(
        sbom_scan_id,
        repo.id,
        [
            {
                "name": "requests",
                "version": "2.32.0",
                "purl": "pkg:pypi/requests@2.32.0",
                "type": "library",
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            }
        ],
    )

    grype_scan_id = await db.save_grype_scan(repo.id, "/tmp/grype.json", 1)
    await db.save_grype_findings(
        grype_scan_id,
        repo.id,
        [
            {
                "vulnerability": {
                    "id": "CVE-2024-0001",
                    "severity": "High",
                    "description": "Test vuln",
                    "urls": ["https://example.com/CVE-2024-0001"],
                    "fix": {"versions": ["2.32.1"]},
                    "cvss": [{"metrics": {"baseScore": 8.1}}],
                },
                "artifact": {
                    "name": "requests",
                    "version": "2.32.0",
                    "type": "python",
                    "locations": [{"path": "requirements.txt"}],
                },
            }
        ],
    )

    codeql_scan_id = await db.save_codeql_scan(repo.id, "python", "/tmp/codeql.sarif", 1)
    await db.save_codeql_findings(
        codeql_scan_id,
        repo.id,
        [
            {
                "ruleId": "py/sql-injection",
                "level": "error",
                "message": {"text": "Possible SQL injection"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": "src/app.py"},
                            "region": {
                                "startLine": 42,
                                "startColumn": 5,
                                "endLine": 42,
                                "endColumn": 20,
                            },
                        }
                    }
                ],
            }
        ],
        {
            "py/sql-injection": {
                "name": "Potential SQL injection",
                "properties": {"tags": ["security", "external/cwe/cwe-89"]},
            }
        },
    )

    cloned = await db.get_cloned_repos()
    saved_repo = await db.get_repo_by_id(repo.id)
    await db.close()

    payload = json.loads(db_path.read_text())

    assert cloned == [
        {
            "id": repo.id,
            "full_name": "test-org/repo-a",
            "name": "repo-a",
            "clone_path": "/data/repos/test-org/repo-a",
            "language": "Python",
            "last_commit_sha": "abc123",
            "default_branch": "main",
            "org_name": "test-org",
        }
    ]
    assert saved_repo.full_name == "test-org/repo-a"
    assert saved_repo.miner_status == "cloned"
    assert payload["meta"]["format"] == "miner-json-v1"
    assert len(payload["repositories"]) == 1
    assert payload["repositories"][0]["clone_path"] == "/data/repos/test-org/repo-a"
    assert payload["gitleaks_findings"][0]["rule_id"] == "github-pat"
    assert payload["gitleaks_findings"][0]["location"] == "app.py:10"
    assert payload["sbom_components"][0]["ecosystem"] == "pypi"
    assert payload["grype_findings"][0]["location"] == "requirements.txt"
    assert payload["grype_findings"][0]["locations"] == ["requirements.txt"]
    assert payload["grype_findings"][0]["fix_versions"] == ["2.32.1"]
    assert payload["codeql_findings"][0]["severity"] == "high"
    assert payload["codeql_findings"][0]["location"] == "src/app.py:42"
