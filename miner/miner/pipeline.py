from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Repository
from .stages.clone import stage_clone
from .stages.codeql import stage_codeql
from .stages.gitleaks import stage_gitleaks
from .stages.grype import stage_grype
from .stages.sbom import stage_sbom
from .stages.types import StageResult, repo_id
from .store import JsonStore

logger = logging.getLogger(__name__)


# Holds configuration values for pipeline workers.
@dataclass
class PipelineConfig:
    clone_root: Path
    output_root: Path
    github_token: str

    clone_workers: int = 1
    gitleaks_workers: int = 1
    sbom_workers: int = 1
    grype_workers: int = 1
    codeql_workers: int = 1

    clone_timeout: int = 1800

    clone_depth: int | None = None


class Pipeline:
    # Initializes the pipeline with config and storage.
    def __init__(self, config: PipelineConfig, db: JsonStore) -> None:
        self.config = config
        self.db = db
        self.results: list[StageResult] = []
        self._lock = asyncio.Lock()
        self._sem_clone = asyncio.Semaphore(config.clone_workers)
        self._sem_gitleaks = asyncio.Semaphore(config.gitleaks_workers)
        self._sem_sbom = asyncio.Semaphore(config.sbom_workers)
        self._sem_grype = asyncio.Semaphore(config.grype_workers)
        self._sem_codeql = asyncio.Semaphore(config.codeql_workers)
        self._codeql_pending: int = 0
        self._codeql_done: int = 0

    # Runs the full pipeline over all repositories in parallel.
    async def run(self, repos: list[Repository]) -> dict[str, Any]:
        self.results = []
        if not repos:
            return {"total_repos": 0, "stages": {}}

        logger.info(
            f"Iniciando pipeline: {len(repos)} repos en paralelo | "
            f"workers clone={self.config.clone_workers} "
            f"gitleaks={self.config.gitleaks_workers} sbom={self.config.sbom_workers} "
            f"grype={self.config.grype_workers} codeql={self.config.codeql_workers}"
        )

        await asyncio.gather(*[self._process_repo(repo) for repo in repos], return_exceptions=True)
        return self._build_summary(repos)

    # Processes a single repository end-to-end.
    async def _process_repo(self, repo: Repository) -> None:
        logger.info(f"[clone] → {repo.full_name}")
        repo_id_value = repo_id(repo)
        await self.db.update_repo_status(repo_id_value, "cloning")

        async with self._sem_clone:
            clone_result = await stage_clone(
                repo=repo,
                clone_root=self.config.clone_root,
                token=self.config.github_token,
                depth=self.config.clone_depth,
                timeout=self.config.clone_timeout,
            )
        await self._record(clone_result)

        if not clone_result.success:
            await self.db.update_repo_status(repo_id_value, "error", error=clone_result.error)
            logger.warning(f"[clone] ✗ {repo.full_name}: {clone_result.error}")
            return

        await self.db.mark_repo_cloned(
            repo_id_value,
            clone_path=clone_result.metadata["clone_path"],
            commit_sha=clone_result.metadata["commit_sha"],
        )
        logger.info(f"[clone] ✓ {repo.full_name}")

        clone_path = Path(clone_result.metadata["clone_path"])

        gitleaks_task = asyncio.create_task(
            self._run_gitleaks(repo, clone_result, clone_path)
        )
        sbom_task = asyncio.create_task(
            self._run_sbom(repo, clone_result, clone_path)
        )
        codeql_task = asyncio.create_task(
            self._run_codeql(repo, clone_result)
        )

        sbom_result = await sbom_task
        tasks = [gitleaks_task, codeql_task]
        if sbom_result and sbom_result.success:
            grype_task = asyncio.create_task(self._run_grype(repo, sbom_result))
            tasks.append(grype_task)

        await asyncio.gather(*tasks)

    # Runs gitleaks scans and persists findings.
    async def _run_gitleaks(
        self,
        repo: Repository,
        clone_result: StageResult,
        clone_path: Path,
    ) -> StageResult:
        output_dir = self.config.output_root / repo.name / "gitleaks"

        logger.info(f"[gitleaks] → {clone_result.repo_full_name}")
        async with self._sem_gitleaks:
            result = await stage_gitleaks(
                repo=repo,
                clone_path=clone_path,
                output_dir=output_dir,
            )
        await self._record(result)

        if result.success:
            report_path_str = result.metadata.get("report_path")
            findings: list[dict[str, Any]] = []
            if report_path_str:
                try:
                    raw = json.loads(Path(report_path_str).read_text())
                    if isinstance(raw, list):
                        findings = [item for item in raw if isinstance(item, dict)]
                except Exception:
                    pass

            repo_id_value = repo_id(repo)
            scan_id = await self.db.save_gitleaks_scan(
                repo_id=repo_id_value,
                commit_sha=clone_result.metadata.get("commit_sha"),
                report_path=report_path_str,
                findings_count=len(findings),
            )
            if findings:
                await self.db.save_gitleaks_findings(scan_id, repo_id_value, findings)
            logger.info(
                f"[gitleaks] ✓ {clone_result.repo_full_name} — {len(findings)} findings"
            )
        else:
            logger.warning(f"[gitleaks] ✗ {clone_result.repo_full_name}: {result.error}")

        return result

    # Generates SBOMs and persists components.
    async def _run_sbom(
        self,
        repo: Repository,
        clone_result: StageResult,
        clone_path: Path,
    ) -> StageResult:
        output_dir = self.config.output_root / repo.name / "sbom"

        logger.info(f"[sbom] → {clone_result.repo_full_name}")
        async with self._sem_sbom:
            result = await stage_sbom(
                repo=repo,
                clone_path=clone_path,
                output_dir=output_dir,
            )
        await self._record(result)

        if result.success:
            sbom_path_str = result.metadata.get("sbom_path")
            components: list[dict[str, Any]] = []
            if sbom_path_str:
                try:
                    sbom_data = json.loads(Path(sbom_path_str).read_text())
                    raw_components = sbom_data.get("components", [])
                    if isinstance(raw_components, list):
                        components = [item for item in raw_components if isinstance(item, dict)]
                except Exception:
                    pass

            repo_id_value = repo_id(repo)
            scan_id = await self.db.save_sbom_scan(
                repo_id=repo_id_value,
                sbom_path=sbom_path_str,
                component_count=len(components),
            )
            if components:
                await self.db.save_sbom_components(scan_id, repo_id_value, components)
            logger.info(
                f"[sbom] ✓ {clone_result.repo_full_name} — {len(components)} componentes"
            )
        else:
            logger.warning(f"[sbom] ✗ {clone_result.repo_full_name}: {result.error}")

        return result

    # Scans SBOMs with grype and persists findings.
    async def _run_grype(self, repo: Repository, sbom_result: StageResult) -> StageResult:
        sbom_path = Path(sbom_result.metadata["sbom_path"])
        output_dir = self.config.output_root / repo.name / "grype"

        logger.info(f"[grype] → {sbom_result.repo_full_name}")
        async with self._sem_grype:
            result = await stage_grype(
                repo=repo,
                sbom_path=sbom_path,
                output_dir=output_dir,
            )
        await self._record(result)

        if result.success:
            report_path_str = result.metadata.get("report_path")
            matches: list[dict[str, Any]] = []
            if report_path_str:
                try:
                    grype_data = json.loads(Path(report_path_str).read_text())
                    raw_matches = grype_data.get("matches", [])
                    if isinstance(raw_matches, list):
                        matches = [item for item in raw_matches if isinstance(item, dict)]
                except Exception:
                    pass

            critical = sum(
                1
                for m in matches
                if m.get("vulnerability", {}).get("severity", "").lower() == "critical"
            )
            repo_id_value = repo_id(repo)
            scan_id = await self.db.save_grype_scan(
                repo_id=repo_id_value,
                report_path=report_path_str,
                findings_count=len(matches),
            )
            if matches:
                await self.db.save_grype_findings(scan_id, repo_id_value, matches)
            logger.info(
                f"[grype] ✓ {sbom_result.repo_full_name} — "
                f"{len(matches)} vulns ({critical} criticas)"
            )
        else:
            logger.warning(f"[grype] ✗ {sbom_result.repo_full_name}: {result.error}")

        return result

    # Runs CodeQL analysis and persists findings when available.
    async def _run_codeql(self, repo: Repository, clone_result: StageResult) -> StageResult:
        clone_path = self.config.clone_root / repo.org_name / repo.name
        output_dir = self.config.output_root / repo.name / "codeql"

        self._codeql_pending += 1
        logger.info(
            f"[codeql] ⏳ {clone_result.repo_full_name} — "
            f"en cola  ({self._codeql_pending} esperando, {self._codeql_done} listos)"
        )
        async with self._sem_codeql:
            self._codeql_pending -= 1
            logger.info(
                f"[codeql] ▶  {clone_result.repo_full_name} — "
                f"ejecutando  ({self._codeql_pending} en cola, {self._codeql_done} listos)"
            )
            result = await stage_codeql(
                repo=repo,
                clone_path=clone_path,
                output_dir=output_dir,
            )
        await self._record(result)

        if result.success and not result.metadata.get("skipped"):
            results_path_str = result.metadata.get("results_path")
            codeql_results: list[dict[str, Any]] = []
            rules_by_id: dict[str, dict[str, Any]] = {}
            if results_path_str:
                try:
                    sarif = json.loads(Path(results_path_str).read_text())
                    for run in sarif.get("runs", []):
                        if not isinstance(run, Mapping):
                            continue
                        for rule in run.get("tool", {}).get("driver", {}).get("rules", []):
                            if not isinstance(rule, dict) or "id" not in rule:
                                continue
                            rules_by_id[rule["id"]] = rule
                        raw_results = run.get("results", [])
                        if isinstance(raw_results, list):
                            codeql_results.extend(
                                item for item in raw_results if isinstance(item, dict)
                            )
                except Exception:
                    pass

            repo_id_value = repo_id(repo)
            scan_id = await self.db.save_codeql_scan(
                repo_id=repo_id_value,
                language=result.metadata.get("language"),
                report_path=results_path_str,
                findings_count=len(codeql_results),
            )
            if codeql_results:
                await self.db.save_codeql_findings(
                    scan_id, repo_id_value, codeql_results, rules_by_id
                )
            self._codeql_done += 1
            logger.info(
                f"[codeql] ✓  {clone_result.repo_full_name} — "
                f"{len(codeql_results)} findings  "
                f"({result.duration_s:.0f}s | "
                f"{self._codeql_pending} en cola, {self._codeql_done} listos)"
            )
        elif result.metadata.get("skipped"):
            self._codeql_done += 1
            logger.info(
                f"[codeql] ⊘  {clone_result.repo_full_name} — "
                f"{result.metadata.get('reason')}  "
                f"({self._codeql_pending} en cola, {self._codeql_done} listos)"
            )
        else:
            self._codeql_done += 1
            logger.warning(
                f"[codeql] ✗  {clone_result.repo_full_name} — "
                f"{result.error}  "
                f"({self._codeql_pending} en cola, {self._codeql_done} listos)"
            )

        return result

    # Stores a stage result in memory for the final summary.
    async def _record(self, result: StageResult) -> None:
        async with self._lock:
            self.results.append(result)

    # Builds an aggregated summary of all pipeline stages.
    def _build_summary(self, repos: list[Repository]) -> dict[str, Any]:
        stages = ["clone", "gitleaks", "sbom", "grype", "codeql"]
        summary: dict[str, Any] = {"total_repos": len(repos), "stages": {}}

        for stage in stages:
            stage_results = [r for r in self.results if r.stage == stage]
            ok = [r for r in stage_results if r.success]
            fail = [r for r in stage_results if not r.success]
            avg_duration = (
                sum(r.duration_s for r in stage_results) / len(stage_results)
                if stage_results
                else 0
            )
            summary["stages"][stage] = {
                "processed": len(stage_results),
                "ok": len(ok),
                "failed": len(fail),
                "avg_duration_s": round(avg_duration, 1),
            }

        return summary
