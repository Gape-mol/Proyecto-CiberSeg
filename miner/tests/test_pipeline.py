"""
Tests del Pipeline Orchestrator.
Verifican el flujo de datos entre colas sin ejecutar herramientas reales.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miner.models import Repository
from miner.pipeline import Pipeline, PipelineConfig, StageResult, stage_gitleaks, stage_sbom

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        clone_root=tmp_path / "repos",
        output_root=tmp_path / "output",
        github_token="test-token",
        max_concurrent_repos=1,
        clone_timeout=10,
        gitleaks_timeout=10,
        sbom_timeout=10,
        grype_timeout=10,
        codeql_timeout=10,
    )


def make_repo(repo_id: int, name: str, language: str = "Python") -> Repository:
    return Repository(
        id=repo_id,
        org_id=1,
        name=name,
        full_name=f"org/{name}",
        clone_url=f"https://github.com/org/{name}.git",
        language=language,
    )


def make_mock_db(repos: list[Repository]) -> MagicMock:
    """Crea un mock de Database con los métodos que usa el pipeline."""
    db = MagicMock()
    repo_map = {r.id: r for r in repos}

    db.update_repo_status = AsyncMock()
    db.mark_repo_cloned = AsyncMock()
    db.get_repo_by_id = AsyncMock(side_effect=lambda rid: repo_map[rid])
    db.save_gitleaks_scan = AsyncMock(return_value=1)
    db.save_sbom_scan = AsyncMock(return_value=1)
    db.save_grype_scan = AsyncMock(return_value=1)
    db.save_codeql_scan = AsyncMock(return_value=1)
    return db


# ---------------------------------------------------------------------------
# Tests: flujo de colas
# ---------------------------------------------------------------------------

class TestPipelineQueues:

    @patch("miner.pipeline.stage_clone")
    @patch("miner.pipeline.stage_gitleaks")
    @patch("miner.pipeline.stage_sbom")
    @patch("miner.pipeline.stage_grype")
    @patch("miner.pipeline.stage_codeql")
    async def test_all_stages_called_for_successful_repo(
        self,
        mock_codeql,
        mock_grype,
        mock_sbom,
        mock_gitleaks,
        mock_clone,
        pipeline_config,
    ):
        """
        Verifica que un repo que se clona con éxito pase por todas las etapas.
        """
        repo = make_repo(1, "test-repo")
        db = make_mock_db([repo])

        clone_result = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="clone", success=True,
            metadata={"clone_path": "/repos/org/test-repo", "commit_sha": "abc123"},
        )
        sbom_result = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="sbom", success=True,
            metadata={
                "sbom_path": "/output/test-repo/sbom/test-repo-sbom.cdx.json",
                "component_count": 10,
            },
        )

        mock_clone.return_value = clone_result
        mock_gitleaks.return_value = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="gitleaks", success=True,
            metadata={"findings_count": 2, "report_path": "/out/gitleaks.json"},
        )
        mock_sbom.return_value = sbom_result
        mock_grype.return_value = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="grype", success=True,
            metadata={"findings_count": 5, "critical_count": 1, "report_path": "/out/grype.json"},
        )
        mock_codeql.return_value = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="codeql", success=True,
            metadata={
                "language": "python",
                "findings_count": 3,
                "results_path": "/out/codeql.sarif",
            },
        )

        pipeline = Pipeline(config=pipeline_config, db=db)
        summary = await pipeline.run([repo])

        # Verificar que todas las etapas se ejecutaron
        mock_clone.assert_called_once()
        mock_gitleaks.assert_called_once()
        mock_sbom.assert_called_once()
        mock_grype.assert_called_once()
        mock_codeql.assert_called_once()

        # Verificar resumen
        assert summary["total_repos"] == 1
        assert summary["stages"]["clone"]["ok"] == 1
        assert summary["stages"]["gitleaks"]["ok"] == 1
        assert summary["stages"]["sbom"]["ok"] == 1
        assert summary["stages"]["grype"]["ok"] == 1
        assert summary["stages"]["codeql"]["ok"] == 1

    @patch("miner.pipeline.stage_clone")
    @patch("miner.pipeline.stage_gitleaks")
    @patch("miner.pipeline.stage_sbom")
    @patch("miner.pipeline.stage_grype")
    @patch("miner.pipeline.stage_codeql")
    async def test_failed_clone_skips_downstream_stages(
        self,
        mock_codeql,
        mock_grype,
        mock_sbom,
        mock_gitleaks,
        mock_clone,
        pipeline_config,
    ):
        """
        Si el clonado falla, gitleaks y sbom NO deben ejecutarse para ese repo.
        """
        repo = make_repo(1, "broken-repo")
        db = make_mock_db([repo])

        mock_clone.return_value = StageResult(
            repo_id=1, repo_full_name="org/broken-repo", stage="clone",
            success=False, error="Connection timeout",
        )

        pipeline = Pipeline(config=pipeline_config, db=db)
        summary = await pipeline.run([repo])

        mock_clone.assert_called_once()
        mock_gitleaks.assert_not_called()
        mock_sbom.assert_not_called()
        mock_grype.assert_not_called()
        mock_codeql.assert_not_called()

        assert summary["stages"]["clone"]["failed"] == 1

    @patch("miner.pipeline.stage_clone")
    @patch("miner.pipeline.stage_gitleaks")
    @patch("miner.pipeline.stage_sbom")
    @patch("miner.pipeline.stage_grype")
    @patch("miner.pipeline.stage_codeql")
    async def test_failed_sbom_skips_grype_and_codeql(
        self,
        mock_codeql,
        mock_grype,
        mock_sbom,
        mock_gitleaks,
        mock_clone,
        pipeline_config,
    ):
        """
        Si SBOM falla, Grype y CodeQL no se ejecutan.
        Gitleaks sí (no depende del SBOM).
        """
        repo = make_repo(1, "test-repo")
        db = make_mock_db([repo])

        clone_result = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="clone", success=True,
            metadata={"clone_path": "/repos/org/test-repo", "commit_sha": "abc"},
        )
        mock_clone.return_value = clone_result
        mock_gitleaks.return_value = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="gitleaks", success=True,
            metadata={"findings_count": 0},
        )
        mock_sbom.return_value = StageResult(
            repo_id=1, repo_full_name="org/test-repo", stage="sbom",
            success=False, error="syft not found",
        )

        pipeline = Pipeline(config=pipeline_config, db=db)
        await pipeline.run([repo])

        mock_gitleaks.assert_called_once()   # sí se ejecutó
        mock_sbom.assert_called_once()
        mock_grype.assert_not_called()       # no se ejecutaron
        mock_codeql.assert_not_called()

    @patch("miner.pipeline.stage_clone")
    @patch("miner.pipeline.stage_gitleaks")
    @patch("miner.pipeline.stage_sbom")
    @patch("miner.pipeline.stage_grype")
    @patch("miner.pipeline.stage_codeql")
    async def test_multiple_repos_all_processed(
        self,
        mock_codeql,
        mock_grype,
        mock_sbom,
        mock_gitleaks,
        mock_clone,
        pipeline_config,
    ):
        """
        Con N repos, todas las etapas deben procesarse N veces.
        """
        repos = [make_repo(i, f"repo-{i}") for i in range(1, 4)]
        db = make_mock_db(repos)

        def make_results(stage, success=True, sbom_path="/out/sbom.json"):
            return StageResult(
                repo_id=1, repo_full_name="org/repo", stage=stage, success=success,
                metadata={
                    "clone_path": "/repos/org/repo",
                    "commit_sha": "abc",
                    "sbom_path": sbom_path,
                    "component_count": 5,
                    "findings_count": 1,
                    "critical_count": 0,
                    "report_path": "/out/report.json",
                    "language": "python",
                    "results_path": "/out/sarif",
                },
            )

        mock_clone.side_effect = [make_results("clone") for _ in repos]
        mock_gitleaks.side_effect = [make_results("gitleaks") for _ in repos]
        mock_sbom.side_effect = [make_results("sbom") for _ in repos]
        mock_grype.side_effect = [make_results("grype") for _ in repos]
        mock_codeql.side_effect = [make_results("codeql") for _ in repos]

        pipeline = Pipeline(config=pipeline_config, db=db)
        summary = await pipeline.run(repos)

        assert mock_clone.call_count == 3
        assert mock_gitleaks.call_count == 3
        assert mock_sbom.call_count == 3
        assert mock_grype.call_count == 3
        assert mock_codeql.call_count == 3
        assert summary["total_repos"] == 3


# ---------------------------------------------------------------------------
# Tests: etapas individuales (unit)
# ---------------------------------------------------------------------------

class TestStageGitleaks:

    async def test_returns_error_when_gitleaks_not_installed(self, tmp_path):
        repo = make_repo(1, "test")
        with patch("shutil.which", return_value=None):
            result = await stage_gitleaks(repo, tmp_path, tmp_path)
        assert result.success is False
        assert "gitleaks no encontrado" in result.error


class TestStageSbom:

    async def test_returns_error_when_syft_not_installed(self, tmp_path):
        repo = make_repo(1, "test")
        with patch("shutil.which", return_value=None):
            result = await stage_sbom(repo, tmp_path, tmp_path)
        assert result.success is False
        assert "syft no encontrado" in result.error
