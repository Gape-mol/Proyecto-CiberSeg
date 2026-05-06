from __future__ import annotations

from unittest.mock import patch

import pytest


class TestAIDevImportError:
    """Test que verifica el comportamiento cuando datasets no está instalado."""

    def test_import_error_message_is_clear(self) -> None:
        """Verifica que el mensaje de error menciona claramente datasets."""
        from miner.aidev import AIDevClient

        with patch("datasets.load_dataset", side_effect=ImportError("No module named 'datasets'")):
            client = AIDevClient()
            with pytest.raises(ImportError, match="datasets"):
                client._load_dataset()


class TestAIDevClientListOrganizations:
    """Tests para list_organizations() con datos mockeados."""

    def test_list_organizations_returns_correct_structure(self) -> None:
        """Verifica que retorna lista de AIDevOrg con login y repo_count."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 100.0},
            {"full_name": "org1/repo-b", "stars": 50.0},
            {"full_name": "org2/repo-a", "stars": 200.0},
            {"full_name": "org3/repo-a", "stars": 10.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            orgs = client.list_organizations()

            assert len(orgs) == 3
            org_dict = {o.login: o.repo_count for o in orgs}
            assert org_dict["org1"] == 2
            assert org_dict["org2"] == 1
            assert org_dict["org3"] == 1

    def test_list_organizations_sorted_by_repo_count(self) -> None:
        """Verifica que las organizaciones están ordenadas por repo_count descendente."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "small-org/repo-a", "stars": 10.0},
            {"full_name": "small-org/repo-b", "stars": 5.0},
            {"full_name": "big-org/repo-a", "stars": 100.0},
            {"full_name": "big-org/repo-b", "stars": 90.0},
            {"full_name": "big-org/repo-c", "stars": 80.0},
            {"full_name": "medium-org/repo-a", "stars": 50.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            orgs = client.list_organizations(min_stars=0)

            assert len(orgs) == 3

            big_org = next(o for o in orgs if o.login == "big-org")
            assert big_org.repo_count == 3

            medium_org = next(o for o in orgs if o.login == "medium-org")
            assert medium_org.repo_count == 1

            small_org = next(o for o in orgs if o.login == "small-org")
            assert small_org.repo_count == 2

            counts = [o.repo_count for o in orgs]
            assert counts == [3, 2, 1]


class TestAIDevClientMinStarsFilter:
    """Tests para el filtro min_stars."""

    def test_filter_repos_by_min_stars(self) -> None:
        """Verifica que filtra repos con menos stars que el mínimo."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "popular/repo-a", "stars": 100.0},
            {"full_name": "popular/repo-b", "stars": 50.0},
            {"full_name": "popular/repo-c", "stars": 10.0},
            {"full_name": "unpopular/repo-a", "stars": 5.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            orgs = client.list_organizations(min_stars=50)

            assert len(orgs) == 1
            assert orgs[0].login == "popular"
            assert orgs[0].repo_count == 2

    def test_min_stars_zero_returns_all(self) -> None:
        """Verifica que min_stars=0 retorna todas las organizaciones."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 0.0},
            {"full_name": "org2/repo-a", "stars": 1.0},
            {"full_name": "org3/repo-a", "stars": None},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            orgs = client.list_organizations(min_stars=0)

            assert len(orgs) == 3


class TestAIDevClientOrgExists:
    """Tests para org_exists()."""

    def test_org_exists_returns_true_for_existing_org(self) -> None:
        """Verifica que retorna True para organización en el dataset."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "existing-org/repo-a", "stars": 100.0},
            {"full_name": "another-org/repo-a", "stars": 50.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            assert client.org_exists("existing-org") is True
            assert client.org_exists("another-org") is True

    def test_org_exists_returns_false_for_non_existing_org(self) -> None:
        """Verifica que retorna False para organización no existente."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "existing-org/repo-a", "stars": 100.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            assert client.org_exists("non-existing-org") is False


class TestAIDevClientIterRepos:
    """Tests para iter_repos()."""

    def test_iter_repos_applies_org_filter(self) -> None:
        """Verifica que filtra correctamente por organización."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 100.0},
            {"full_name": "org2/repo-b", "stars": 50.0},
            {"full_name": "org1/repo-c", "stars": 30.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            repos = list(client.iter_repos(org_filter="org1"))

            assert len(repos) == 2
            assert all(r["owner"]["login"] == "org1" for r in repos)

    def test_iter_repos_applies_min_stars_filter(self) -> None:
        """Verifica que filtra correctamente por min_stars."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 100.0},
            {"full_name": "org1/repo-b", "stars": 50.0},
            {"full_name": "org1/repo-c", "stars": 10.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            repos = list(client.iter_repos(min_stars=50))

            assert len(repos) == 2

    def test_iter_repos_combined_filters(self) -> None:
        """Verifica que aplica ambos filtros simultáneamente."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 100.0},
            {"full_name": "org1/repo-b", "stars": 50.0},
            {"full_name": "org2/repo-c", "stars": 100.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            repos = list(client.iter_repos(org_filter="org1", min_stars=75))

            assert len(repos) == 1
            assert repos[0]["owner"]["login"] == "org1"
            assert repos[0]["stargazers_count"] == 100

    def test_iter_repos_adds_normalized_fields(self) -> None:
        """Verifica que iter_repos añade los campos necesarios para Repository.from_api()."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/my-repo", "stars": 42.0, "forks": 3.0, "language": "Python"},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            repos = list(client.iter_repos())

            assert len(repos) == 1
            r = repos[0]
            assert r["name"] == "my-repo"
            assert r["owner"] == {"login": "org1"}
            assert r["stargazers_count"] == 42
            assert r["forks_count"] == 3
            assert r["clone_url"] == "https://github.com/org1/my-repo.git"


class TestAIDevClientEdgeCases:
    """Tests para casos edge."""

    def test_handles_missing_full_name(self) -> None:
        """Verifica que ignora repos sin full_name."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 100.0},
            {"stars": 50.0},               # sin full_name
            {"full_name": None, "stars": 30.0},  # full_name nulo
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            orgs = client.list_organizations()

            assert len(orgs) == 1
            assert orgs[0].login == "org1"

    def test_handles_null_stars(self) -> None:
        """Verifica que maneja valores null en stars."""
        from miner.aidev import AIDevClient

        mock_dataset = [
            {"full_name": "org1/repo-a", "stars": 100.0},
            {"full_name": "org1/repo-b", "stars": None},
            {"full_name": "org1/repo-c", "stars": 0.0},
        ]

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = mock_dataset
            client = AIDevClient()
            orgs = client.list_organizations(min_stars=50)

            assert len(orgs) == 1
            assert orgs[0].login == "org1"

    def test_lazy_loading_dataset(self) -> None:
        """Verifica que el dataset se carga solo cuando se necesita."""
        from miner.aidev import AIDevClient

        with patch("datasets.load_dataset") as mock_load:
            mock_load.return_value = []
            client = AIDevClient()

            mock_load.assert_not_called()

            client._load_dataset()
            mock_load.assert_called_once()

            client._load_dataset()
            mock_load.assert_called_once()
