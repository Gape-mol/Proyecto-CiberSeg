from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from ..models import Repository
from .types import StageResult, repo_id

logger = logging.getLogger(__name__)


# Runs gitleaks on a cloned repo and returns a stage result.
async def stage_gitleaks(
    repo: Repository,
    clone_path: Path,
    output_dir: Path,
    timeout: int = 300,
) -> StageResult:
    repo_id_value = repo_id(repo)
    if not shutil.which("gitleaks"):
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=False,
            error="gitleaks no encontrado en PATH. Instala: https://github.com/gitleaks/gitleaks",
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
            repo_id=repo_id_value,
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
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=False,
            error=f"Timeout despues de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="gitleaks",
            success=False,
            error=str(e),
        )
