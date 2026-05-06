from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from ..models import Repository
from .types import StageResult, repo_id

logger = logging.getLogger(__name__)


# Scans a SBOM with Grype and returns a stage result.
async def stage_grype(
    repo: Repository,
    sbom_path: Path,
    output_dir: Path,
    timeout: int = 180,
) -> StageResult:
    repo_id_value = repo_id(repo)
    if not shutil.which("grype"):
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error="grype no encontrado en PATH. Instala: https://github.com/anchore/grype",
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
            f"({critical_count} criticas) en {duration:.1f}s"
        )
        return StageResult(
            repo_id=repo_id_value,
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
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error=f"Timeout despues de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error=str(e),
        )
