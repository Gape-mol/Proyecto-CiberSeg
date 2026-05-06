from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from ..models import Repository
from .types import StageResult, repo_id

logger = logging.getLogger(__name__)


# Generates a CycloneDX SBOM with Syft and returns a stage result.
async def stage_sbom(
    repo: Repository,
    clone_path: Path,
    output_dir: Path,
    timeout: int = 180,
) -> StageResult:
    repo_id_value = repo_id(repo)
    if not shutil.which("syft"):
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=False,
            error="syft no encontrado en PATH. Instala: https://github.com/anchore/syft",
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
                repo_id=repo_id_value,
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
            repo_id=repo_id_value,
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
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=False,
            error=f"Timeout despues de {timeout}s",
        )
    except Exception as e:
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="sbom",
            success=False,
            error=str(e),
        )
