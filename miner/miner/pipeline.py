from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .db import Database
from .models import Repository

logger = logging.getLogger(__name__)

_DONE = None


@dataclass
class StageResult:
    repo_id: int
    repo_full_name: str
    stage: str
    success: bool
    duration_s: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _repo_id(repo: Repository) -> int:
    assert repo.id is not None
    return repo.id


async def stage_clone(
    repo: Repository,
    clone_root: Path,
    token: str,
    depth: int | None,
    timeout: int,
) -> StageResult:
    """Wrapper de clone_or_update_repo que devuelve StageResult."""
    from .miner import clone_or_update_repo

    repo_id = _repo_id(repo)
    t0 = asyncio.get_event_loop().time()
    result = await clone_or_update_repo(
        repo=repo,
        clone_root=clone_root,
        token=token,
        depth=depth,
        timeout=timeout,
    )
    duration = asyncio.get_event_loop().time() - t0

    return StageResult(
        repo_id=repo_id,
        repo_full_name=repo.full_name,
        stage="clone",
        success=result.success,
        duration_s=duration,
        error=result.error,
        metadata={
            "clone_path": str(result.clone_path) if result.clone_path else None,
            "commit_sha": result.commit_sha,
        },
    )


async def stage_gitleaks(
    repo: Repository,
    clone_path: Path,
    output_dir: Path,
    timeout: int = 300,
) -> StageResult:
    repo_id = _repo_id(repo)
    if not shutil.which("gitleaks"):
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=False,
            error="gitleaks no encontrado en PATH. Instalá: https://github.com/gitleaks/gitleaks",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{repo.name}-gitleaks.json"

    cmd = [
        "gitleaks",
        "detect",
        "--source",
        str(clone_path),
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
        "--no-banner",
        "--exit-code",
        "0",
    ]

    t0 = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration = asyncio.get_event_loop().time() - t0

        findings_count = 0
        if report_path.exists():
            try:
                findings = json.loads(report_path.read_text())
                findings_count = len(findings) if isinstance(findings, list) else 0
            except json.JSONDecodeError:
                pass

        logger.info(f"[{repo.full_name}] Gitleaks: {findings_count} findings en {duration:.1f}s")
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=True,
            duration_s=duration,
            metadata={
                "findings_count": findings_count,
                "report_path": str(report_path),
            },
        )

    except TimeoutError:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=False,
            error=f"Timeout después de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=False,
            error=str(e),
        )


async def stage_sbom(
    repo: Repository,
    clone_path: Path,
    output_dir: Path,
    timeout: int = 180,
) -> StageResult:
    repo_id = _repo_id(repo)
    if not shutil.which("syft"):
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=False,
            error="syft no encontrado en PATH. Instalá: https://github.com/anchore/syft",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = output_dir / f"{repo.name}-sbom.cdx.json"

    cmd = [
        "syft",
        str(clone_path),
        "--output",
        f"cyclonedx-json={sbom_path}",
        "--quiet",
    ]

    t0 = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration = asyncio.get_event_loop().time() - t0

        if proc.returncode != 0:
            return StageResult(
                repo_id=repo_id,
                repo_full_name=repo.full_name,
                stage="sbom",
                success=False,
                duration_s=duration,
                error=stderr.decode().strip(),
            )

        component_count = 0
        if sbom_path.exists():
            try:
                sbom_data = json.loads(sbom_path.read_text())
                component_count = len(sbom_data.get("components", []))
            except json.JSONDecodeError:
                pass

        logger.info(f"[{repo.full_name}] SBOM: {component_count} componentes en {duration:.1f}s")
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=True,
            duration_s=duration,
            metadata={
                "sbom_path": str(sbom_path),
                "component_count": component_count,
            },
        )

    except TimeoutError:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=False,
            error=f"Timeout después de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=False,
            error=str(e),
        )


async def stage_grype(
    repo: Repository,
    sbom_path: Path,
    output_dir: Path,
    timeout: int = 180,
) -> StageResult:
    repo_id = _repo_id(repo)
    """
    Analiza el SBOM con Grype para encontrar CVEs en dependencias.
    Recibe el path al SBOM CycloneDX generado por stage_sbom.
    """
    if not shutil.which("grype"):
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error="grype no encontrado en PATH. Instalá: https://github.com/anchore/grype",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{repo.name}-grype.json"

    cmd = [
        "grype",
        f"sbom:{sbom_path}",
        "--output",
        "json",
        "--file",
        str(report_path),
        "--quiet",
    ]

    t0 = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration = asyncio.get_event_loop().time() - t0

        findings_count = 0
        critical_count = 0
        if report_path.exists():
            try:
                grype_data = json.loads(report_path.read_text())
                matches = grype_data.get("matches", [])
                findings_count = len(matches)
                critical_count = sum(
                    1
                    for m in matches
                    if m.get("vulnerability", {}).get("severity", "").lower() == "critical"
                )
            except json.JSONDecodeError:
                pass

        logger.info(
            f"[{repo.full_name}] Grype: {findings_count} vulnerabilidades "
            f"({critical_count} críticas) en {duration:.1f}s"
        )
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="grype",
            success=True,
            duration_s=duration,
            metadata={
                "findings_count": findings_count,
                "critical_count": critical_count,
                "report_path": str(report_path),
            },
        )

    except TimeoutError:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error=f"Timeout después de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error=str(e),
        )


CODEQL_LANGUAGE_MAP = {
    "Python": "python",
    "JavaScript": "javascript",
    "TypeScript": "javascript",
    "Java": "java",
    "Kotlin": "java",
    "C#": "csharp",
    "Go": "go",
    "Ruby": "ruby",
    "Swift": "swift",
    "C": "cpp",
    "C++": "cpp",
}

# Lenguajes que no necesitan compilación — usan --build-mode=none
_CODEQL_NO_BUILD = {"javascript", "python", "ruby"}


async def stage_codeql(
    repo: Repository,
    clone_path: Path,
    output_dir: Path,
    timeout: int = 1800,
) -> StageResult:
    """
    Ejecuta análisis estático con CodeQL.
    Solo analiza repos cuyo lenguaje principal tenga soporte en CodeQL.
    """
    repo_id = _repo_id(repo)
    if not shutil.which("codeql"):
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=False,
            error="codeql no encontrado en PATH. Instalá: https://github.com/github/codeql-action",
        )

    # Determinar el lenguaje CodeQL
    codeql_lang = CODEQL_LANGUAGE_MAP.get(repo.language or "")
    if not codeql_lang:
        logger.info(
            f"[{repo.full_name}] CodeQL: lenguaje '{repo.language}' no soportado, saltando."
        )
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=True,
            metadata={"skipped": True, "reason": f"Lenguaje no soportado: {repo.language}"},
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / f"{repo.name}-codeql-db"
    results_path = output_dir / f"{repo.name}-codeql.sarif"

    t0 = asyncio.get_event_loop().time()
    try:
        # Paso 1: Crear la base de datos de CodeQL
        create_cmd = [
            "codeql",
            "database",
            "create",
            str(db_path),
            "--language", codeql_lang,
            "--source-root", str(clone_path),
            "--overwrite",
            "--quiet",
        ]
        if codeql_lang in _CODEQL_NO_BUILD:
            create_cmd += ["--build-mode", "none"]
        proc = await asyncio.create_subprocess_exec(
            *create_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout // 2)

        if proc.returncode != 0:
            return StageResult(
                repo_id=repo_id,
                repo_full_name=repo.full_name,
                stage="codeql",
                success=False,
                error=f"codeql database create falló: {stderr.decode().strip()[:500]}",
            )

        # Paso 2: Ejecutar las queries de seguridad
        analyze_cmd = [
            "codeql",
            "database",
            "analyze",
            str(db_path),
            f"{codeql_lang}-security-and-quality",
            "--format",
            "sarif-latest",
            "--output",
            str(results_path),
            "--quiet",
        ]
        proc = await asyncio.create_subprocess_exec(
            *analyze_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout // 2)
        duration = asyncio.get_event_loop().time() - t0

        if proc.returncode != 0:
            return StageResult(
                repo_id=repo_id,
                repo_full_name=repo.full_name,
                stage="codeql",
                success=False,
                duration_s=duration,
                error=f"codeql analyze falló: {stderr.decode().strip()[:500]}",
            )

        # Contar findings en el SARIF
        findings_count = 0
        if results_path.exists():
            try:
                sarif = json.loads(results_path.read_text())
                for run in sarif.get("runs", []):
                    findings_count += len(run.get("results", []))
            except json.JSONDecodeError:
                pass

        logger.info(
            f"[{repo.full_name}] CodeQL: {findings_count} findings "
            f"({codeql_lang}) en {duration:.1f}s"
        )
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=True,
            duration_s=duration,
            metadata={
                "language": codeql_lang,
                "findings_count": findings_count,
                "results_path": str(results_path),
            },
        )

    except TimeoutError:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=False,
            error=f"Timeout después de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=False,
            error=str(e),
        )


@dataclass
class PipelineConfig:
    clone_root: Path
    output_root: Path
    github_token: str

    clone_workers: int = 3
    gitleaks_workers: int = 2
    sbom_workers: int = 2
    grype_workers: int = 2
    codeql_workers: int = 2

    clone_timeout: int = 600
    gitleaks_timeout: int = 300
    sbom_timeout: int = 180
    grype_timeout: int = 180
    codeql_timeout: int = 1800

    clone_depth: int | None = None


class Pipeline:
    def __init__(self, config: PipelineConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self.results: list[StageResult] = []
        self._lock = asyncio.Lock()

    async def run(self, repos: list[Repository]) -> dict[str, Any]:
        """
        Pipeline streaming: cada repo avanza etapa a etapa en cuanto termina
        la anterior, sin esperar a que todos los repos completen cada fase.

        Los coordinadores (_after_clone, _after_sbom) inyectan los sentineles
        downstream solo cuando todos sus workers productores terminaron,
        garantizando que ningún worker cierre la cola antes de tiempo.
        Todos los workers corren en un único asyncio.gather desde el inicio.
        """
        if not repos:
            return {"total": 0, "stages": {}}

        q_clone: asyncio.Queue[Repository | None] = asyncio.Queue()
        q_gitleaks: asyncio.Queue[StageResult | None] = asyncio.Queue()
        q_sbom: asyncio.Queue[StageResult | None] = asyncio.Queue()
        q_grype: asyncio.Queue[StageResult | None] = asyncio.Queue()
        q_codeql: asyncio.Queue[StageResult | None] = asyncio.Queue()

        logger.info(
            f"Iniciando pipeline: {len(repos)} repos | "
            f"workers clone={self.config.clone_workers} "
            f"gitleaks={self.config.gitleaks_workers} "
            f"sbom={self.config.sbom_workers} "
            f"grype={self.config.grype_workers} "
            f"codeql={self.config.codeql_workers}"
        )

        for repo in repos:
            await q_clone.put(repo)
        for _ in range(self.config.clone_workers):
            await q_clone.put(_DONE)

        async def _after_clone() -> None:
            await asyncio.gather(
                *[
                    self._worker_clone(q_clone, q_gitleaks, q_sbom)
                    for _ in range(self.config.clone_workers)
                ]
            )
            for _ in range(self.config.gitleaks_workers):
                await q_gitleaks.put(_DONE)
            for _ in range(self.config.sbom_workers):
                await q_sbom.put(_DONE)

        async def _after_sbom() -> None:
            await asyncio.gather(
                *[
                    self._worker_sbom(q_sbom, q_grype, q_codeql)
                    for _ in range(self.config.sbom_workers)
                ]
            )
            for _ in range(self.config.grype_workers):
                await q_grype.put(_DONE)
            for _ in range(self.config.codeql_workers):
                await q_codeql.put(_DONE)

        await asyncio.gather(
            _after_clone(),
            _after_sbom(),
            *[self._worker_gitleaks(q_gitleaks) for _ in range(self.config.gitleaks_workers)],
            *[self._worker_grype(q_grype) for _ in range(self.config.grype_workers)],
            *[self._worker_codeql(q_codeql) for _ in range(self.config.codeql_workers)],
        )

        return self._build_summary(repos)

    async def _worker_clone(
        self,
        in_q: asyncio.Queue[Repository | None],
        out_gitleaks: asyncio.Queue[StageResult | None],
        out_sbom: asyncio.Queue[StageResult | None],
    ) -> None:
        while True:
            repo: Repository | None = await in_q.get()
            if repo is _DONE:
                break

            logger.info(f"[clone] → {repo.full_name}")
            repo_id = _repo_id(repo)
            await self.db.update_repo_status(repo_id, "cloning")

            result = await stage_clone(
                repo=repo,
                clone_root=self.config.clone_root,
                token=self.config.github_token,
                depth=self.config.clone_depth,
                timeout=self.config.clone_timeout,
            )
            await self._record(result)

            if result.success:
                await self.db.mark_repo_cloned(
                    repo_id,
                    clone_path=result.metadata["clone_path"],
                    commit_sha=result.metadata["commit_sha"],
                )
                logger.info(f"[clone] ✓ {repo.full_name}")
                await out_gitleaks.put(result)
                await out_sbom.put(result)
            else:
                await self.db.update_repo_status(repo_id, "error", error=result.error)
                logger.warning(f"[clone] ✗ {repo.full_name}: {result.error}")

    async def _worker_gitleaks(self, in_q: asyncio.Queue[StageResult | None]) -> None:
        while True:
            clone_result: StageResult | None = await in_q.get()
            if clone_result is _DONE:
                break

            repo = await self.db.get_repo_by_id(clone_result.repo_id)
            clone_path = Path(clone_result.metadata["clone_path"])
            output_dir = self.config.output_root / repo.name / "gitleaks"

            logger.info(f"[gitleaks] → {clone_result.repo_full_name}")
            result = await stage_gitleaks(
                repo=repo,
                clone_path=clone_path,
                output_dir=output_dir,
                timeout=self.config.gitleaks_timeout,
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

                repo_id = _repo_id(repo)
                scan_id = await self.db.save_gitleaks_scan(
                    repo_id=repo_id,
                    commit_sha=clone_result.metadata.get("commit_sha"),
                    report_path=report_path_str,
                    findings_count=len(findings),
                )
                if findings:
                    await self.db.save_gitleaks_findings(scan_id, repo_id, findings)
                logger.info(
                    f"[gitleaks] ✓ {clone_result.repo_full_name} — {len(findings)} findings"
                )
            else:
                logger.warning(f"[gitleaks] ✗ {clone_result.repo_full_name}: {result.error}")

    async def _worker_sbom(
        self,
        in_q: asyncio.Queue[StageResult | None],
        out_grype: asyncio.Queue[StageResult | None],
        out_codeql: asyncio.Queue[StageResult | None],
    ) -> None:
        while True:
            clone_result: StageResult | None = await in_q.get()
            if clone_result is _DONE:
                break

            repo = await self.db.get_repo_by_id(clone_result.repo_id)
            clone_path = Path(clone_result.metadata["clone_path"])
            output_dir = self.config.output_root / repo.name / "sbom"

            logger.info(f"[sbom] → {clone_result.repo_full_name}")
            result = await stage_sbom(
                repo=repo,
                clone_path=clone_path,
                output_dir=output_dir,
                timeout=self.config.sbom_timeout,
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

                repo_id = _repo_id(repo)
                scan_id = await self.db.save_sbom_scan(
                    repo_id=repo_id,
                    sbom_path=sbom_path_str,
                    component_count=len(components),
                )
                if components:
                    await self.db.save_sbom_components(scan_id, repo_id, components)
                await out_grype.put(result)
                await out_codeql.put(result)
                logger.info(
                    f"[sbom] ✓ {clone_result.repo_full_name} — {len(components)} componentes"
                )
            else:
                logger.warning(f"[sbom] ✗ {clone_result.repo_full_name}: {result.error}")

    async def _worker_grype(self, in_q: asyncio.Queue[StageResult | None]) -> None:
        while True:
            sbom_result: StageResult | None = await in_q.get()
            if sbom_result is _DONE:
                break

            repo = await self.db.get_repo_by_id(sbom_result.repo_id)
            sbom_path = Path(sbom_result.metadata["sbom_path"])
            output_dir = self.config.output_root / repo.name / "grype"

            logger.info(f"[grype] → {sbom_result.repo_full_name}")
            result = await stage_grype(
                repo=repo,
                sbom_path=sbom_path,
                output_dir=output_dir,
                timeout=self.config.grype_timeout,
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
                    1 for m in matches
                    if m.get("vulnerability", {}).get("severity", "").lower() == "critical"
                )
                repo_id = _repo_id(repo)
                scan_id = await self.db.save_grype_scan(
                    repo_id=repo_id,
                    report_path=report_path_str,
                    findings_count=len(matches),
                )
                if matches:
                    await self.db.save_grype_findings(scan_id, repo_id, matches)
                logger.info(
                    f"[grype] ✓ {sbom_result.repo_full_name} — "
                    f"{len(matches)} vulns ({critical} críticas)"
                )
            else:
                logger.warning(f"[grype] ✗ {sbom_result.repo_full_name}: {result.error}")

    async def _worker_codeql(self, in_q: asyncio.Queue[StageResult | None]) -> None:
        while True:
            sbom_result: StageResult | None = await in_q.get()
            if sbom_result is _DONE:
                break

            repo = await self.db.get_repo_by_id(sbom_result.repo_id)
            clone_path = self.config.clone_root / repo.org_name / repo.name
            output_dir = self.config.output_root / repo.name / "codeql"

            logger.info(f"[codeql] → {sbom_result.repo_full_name}")
            result = await stage_codeql(
                repo=repo,
                clone_path=clone_path,
                output_dir=output_dir,
                timeout=self.config.codeql_timeout,
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

                repo_id = _repo_id(repo)
                scan_id = await self.db.save_codeql_scan(
                    repo_id=repo_id,
                    language=result.metadata.get("language"),
                    report_path=results_path_str,
                    findings_count=len(codeql_results),
                )
                if codeql_results:
                    await self.db.save_codeql_findings(
                        scan_id, repo_id, codeql_results, rules_by_id
                    )
                logger.info(
                    f"[codeql] ✓ {sbom_result.repo_full_name} — "
                    f"{len(codeql_results)} findings"
                )
            elif result.metadata.get("skipped"):
                logger.info(
                    f"[codeql] ⊘ {sbom_result.repo_full_name}: "
                    f"{result.metadata.get('reason')}"
                )
            else:
                logger.warning(f"[codeql] ✗ {sbom_result.repo_full_name}: {result.error}")

    async def _record(self, result: StageResult) -> None:
        async with self._lock:
            self.results.append(result)

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
