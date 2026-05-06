"""
Tests del GitHub Miner.
Usa respx para mockear httpx (sin llamadas reales a GitHub).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from miner.miner import (
    GitHubClient,
    MinerConfig,
    _auth_clone_url,
    _normalize_aidev_row,
    clone_or_update_repo,
)
from miner.models import Organization, Repository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path: Path) -> MinerConfig:
    return MinerConfig(
        github_token="ghp_test_token",
        clone_root=tmp_path / "repos",
        db_path=str(tmp_path / "test.json"),
        clone_workers=2,
        clone_depth=1,
        clone_timeout=30,
    )


@pytest.fixture
def sample_repo_data() -> dict[str, object]:
    return {
        "id": 123456,
        "name": "mi-servicio",
        "full_name": "test-org/mi-servicio",
        "clone_url": "https://github.com/test-org/mi-servicio.git",
        "default_branch": "main",
        "description": "Descripción del repo",
        "language": "Python",
        "visibility": "private",
        "archived": False,
        "stargazers_count": 5,
        "forks_count": 2,
        "size": 1024,
        "pushed_at": "2024-03-15T10:00:00Z",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2024-03-15T10:00:00Z",
    }


# ---------------------------------------------------------------------------
# Tests: GitHubClient
# ---------------------------------------------------------------------------

class TestGitHubClient:

    @respx.mock
    async def test_preflight_check_valid_token(self):
        """Verifica que preflight_check pasa con token válido."""
        respx.get("https://api.github.com/rate_limit").mock(
            return_value=httpx.Response(200, json={"resources": {"core": {"remaining": 5000, "limit": 5000}}})
        )
        client = GitHubClient("test_token")
        await client.preflight_check()  # no debe lanzar excepción

    @respx.mock
    async def test_preflight_check_invalid_token(self):
        """Verifica que preflight_check falla con token inválido."""
        respx.get("https://api.github.com/rate_limit").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )
        client = GitHubClient("bad_token")
        with pytest.raises(RuntimeError, match="inválido"):
            await client.preflight_check()


class TestNormalizeAIDevRow:

    def test_fills_missing_full_name(self):
        row = {"owner": {"login": "org1"}, "name": "repo1", "stargazers_count": 10}
        result = _normalize_aidev_row(row)
        assert result is not None
        assert result["full_name"] == "org1/repo1"

    def test_fills_missing_clone_url(self):
        row = {"owner": {"login": "org1"}, "name": "repo1", "stargazers_count": 10}
        result = _normalize_aidev_row(row)
        assert result is not None
        assert result["clone_url"] == "https://github.com/org1/repo1.git"

    def test_preserves_existing_fields(self):
        row = {
            "owner": {"login": "org1"}, "name": "repo1",
            "full_name": "org1/repo1",
            "clone_url": "https://github.com/org1/repo1.git",
            "stargazers_count": 42,
        }
        result = _normalize_aidev_row(row)
        assert result is not None
        assert result["stargazers_count"] == 42

    def test_returns_none_for_missing_owner(self):
        assert _normalize_aidev_row({"name": "repo1"}) is None

    def test_returns_none_for_missing_name(self):
        assert _normalize_aidev_row({"owner": {"login": "org1"}}) is None


# ---------------------------------------------------------------------------
# Tests: Modelos
# ---------------------------------------------------------------------------

class TestModels:

    def test_repository_from_api(self, sample_repo_data):
        repo = Repository.from_api(sample_repo_data, org_id=1)
        assert repo.full_name == "test-org/mi-servicio"
        assert repo.org_name == "test-org"
        assert repo.language == "Python"
        assert repo.archived is False
        assert repo.stars == 5
        assert repo.github_created_at is not None

    def test_organization_from_api(self):
        data = {"login": "test-org", "id": 999, "html_url": "https://github.com/test-org"}
        org = Organization.from_api(data)
        assert org.name == "test-org"
        assert org.github_id == 999


# ---------------------------------------------------------------------------
# Tests: Clone helpers
# ---------------------------------------------------------------------------

class TestCloneHelpers:

    def test_auth_clone_url_inserts_token(self):
        url = "https://github.com/org/repo.git"
        result = _auth_clone_url(url, "mytoken")
        assert "x-access-token:mytoken@" in result
        assert result.startswith("https://")

    @patch("miner.miner._git_clone", new_callable=AsyncMock)
    @patch("miner.miner._get_head_sha", new_callable=AsyncMock, return_value="abc123")
    async def test_clone_new_repo_success(self, mock_sha, mock_clone, config, tmp_path):
        repo = Repository(
            id=1, org_id=1, name="test-repo", full_name="org/test-repo",
            clone_url="https://github.com/org/test-repo.git",
        )
        result = await clone_or_update_repo(
            repo=repo,
            clone_root=config.clone_root,
            token="token",
            depth=1,
            timeout=30,
        )
        assert result.success is True
        assert result.commit_sha == "abc123"
        mock_clone.assert_called_once()

    @patch("miner.miner._git_clone", new_callable=AsyncMock, side_effect=RuntimeError("timeout"))
    async def test_clone_failure_returns_error(self, mock_clone, config):
        repo = Repository(
            id=1, org_id=1, name="broken", full_name="org/broken",
            clone_url="https://github.com/org/broken.git",
        )
        result = await clone_or_update_repo(
            repo=repo, clone_root=config.clone_root, token="t", depth=1, timeout=10
        )
        assert result.success is False
        assert "timeout" in result.error


# ---------------------------------------------------------------------------
# Tests: MinerConfig
# ---------------------------------------------------------------------------

class TestMinerConfig:

    def test_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc")
        monkeypatch.setenv("AIDEV_ORG_FILTER", "org-a,org-b")
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        monkeypatch.setenv("CLONE_WORKERS", "8")
        monkeypatch.setenv("CLONE_DEPTH", "none")
        monkeypatch.setenv("RUN_CONTINUOUS", "true")
        monkeypatch.setenv("RUN_INTERVAL_SECONDS", "120")

        config = MinerConfig.from_env()
        assert config.github_token == "ghp_abc"
        assert config.org_filter == ["org-a", "org-b"]
        assert config.clone_workers == 8
        assert config.clone_depth is None  # "none" → None
        assert config.continuous is True
        assert config.run_interval_s == 120

    def test_from_env_no_filter_processes_all_orgs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc")
        monkeypatch.delenv("AIDEV_ORG_FILTER", raising=False)
        monkeypatch.delenv("GITHUB_ORG", raising=False)
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))

        config = MinerConfig.from_env()
        assert config.org_filter is None

    def test_from_env_missing_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(OSError, match="GITHUB_TOKEN"):
            MinerConfig.from_env()
