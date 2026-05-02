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
        org_name="test-org",
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
    async def test_list_org_repos_single_page(self, sample_repo_data):
        """Verifica que se listen repos correctamente en una página."""
        respx.get("https://api.github.com/orgs/test-org/repos").mock(
            return_value=httpx.Response(
                200,
                json=[sample_repo_data],
                headers={"Link": ""},  # Sin página siguiente
            )
        )

        client = GitHubClient("test_token")
        repos = []
        async for repo in client.list_org_repos("test-org"):
            repos.append(repo)

        assert len(repos) == 1
        assert repos[0]["full_name"] == "test-org/mi-servicio"

    @respx.mock
    async def test_list_org_repos_pagination(self, sample_repo_data):
        """Verifica que se sigan los headers Link para paginación."""
        page2_data = {**sample_repo_data, "name": "otro-repo", "full_name": "test-org/otro-repo"}

        # Un solo route con side_effect list: primera llamada → página 1,
        # segunda llamada → página 2. Sin esto, el route sin params matchea
        # también la URL con ?page=2, causando un loop infinito.
        respx.get("https://api.github.com/orgs/test-org/repos").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[sample_repo_data],
                    headers={
                        "Link": '<https://api.github.com/orgs/test-org/repos?page=2>; rel="next"'
                    },
                ),
                httpx.Response(200, json=[page2_data], headers={"Link": ""}),
            ]
        )

        client = GitHubClient("test_token")
        repos = [r async for r in client.list_org_repos("test-org")]
        assert len(repos) == 2

    def test_next_link_parses_correctly(self):
        client = GitHubClient("token")
        header = (
            '<https://api.github.com/orgs/x/repos?page=2>; rel="next", '
            '<https://api.github.com/orgs/x/repos?page=5>; rel="last"'
        )
        assert client._next_link(header) == "https://api.github.com/orgs/x/repos?page=2"

    def test_next_link_returns_none_on_last_page(self):
        client = GitHubClient("token")
        header = '<https://api.github.com/orgs/x/repos?page=1>; rel="first"'
        assert client._next_link(header) is None

    def test_next_link_returns_none_on_empty(self):
        assert GitHubClient._next_link("") is None


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
        monkeypatch.setenv("GITHUB_ORG", "mi-org")
        monkeypatch.setenv("CLONE_ROOT", str(tmp_path))
        monkeypatch.setenv("CLONE_WORKERS", "8")
        monkeypatch.setenv("CLONE_DEPTH", "none")
        monkeypatch.setenv("RUN_CONTINUOUS", "true")
        monkeypatch.setenv("RUN_INTERVAL_SECONDS", "120")

        config = MinerConfig.from_env()
        assert config.github_token == "ghp_abc"
        assert config.org_name == "mi-org"
        assert config.clone_workers == 8
        assert config.clone_depth is None  # "none" → None
        assert config.continuous is True
        assert config.run_interval_s == 120

    def test_from_env_missing_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_ORG", "org")
        with pytest.raises(OSError, match="GITHUB_TOKEN"):
            MinerConfig.from_env()
