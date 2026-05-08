from __future__ import annotations

import asyncio
import json
import logging
import os
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

    # --add-cpes-if-none: genera CPEs para paquetes sin ellos, mejora el matching de CVEs
    # --by-cve: agrupa por CVE en vez de por advisory (evita duplicados)
    # GRYPE_DB_VALIDATE_AGE=false: permite usar la DB aunque supere el límite de edad,
    # útil cuando no hay internet o el update falla — los CVEs pueden estar desactualizados
    # pero el análisis igual se puede ejecutar.
    cmd = [
        "grype",
        f"sbom:{sbom_path}",
        "--output", "json",
        "--file", str(report_path),
        "--add-cpes-if-none",
        "--by-cve",
        "--quiet",
    ]

    t0 = asyncio.get_event_loop().time()
    try:
        env = {**os.environ, "GRYPE_DB_VALIDATE_AGE": "false"}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr_bytes = await proc.communicate()
        duration = asyncio.get_event_loop().time() - t0

        stderr_text = stderr_bytes.decode(errors="replace").strip()

        # Grype sale con código != 0 si ocurre un error real (no por encontrar vulns)
        if proc.returncode != 0:
            error_msg = stderr_text or f"grype salió con código {proc.returncode}"
            logger.warning(f"[{repo.full_name}] Grype error (rc={proc.returncode}): {error_msg}")
            return StageResult(
                repo_id=repo_id_value,
                repo_full_name=repo.full_name,
                stage="grype",
                success=False,
                duration_s=duration,
                error=error_msg,
            )

        if stderr_text:
            # Puede incluir avisos de DB desactualizada u otras advertencias útiles
            logger.debug(f"[{repo.full_name}] Grype stderr: {stderr_text[:400]}")

        findings_count = 0
        critical_count = 0
        if not report_path.exists():
            return StageResult(
                repo_id=repo_id_value,
                repo_full_name=repo.full_name,
                stage="grype",
                success=False,
                duration_s=duration,
                error="Grype no generó el reporte de salida",
            )

        db_built = ""
        try:
            grype_data = json.loads(report_path.read_text())
            matches = grype_data.get("matches", [])
            findings_count = len(matches)
            critical_count = sum(
                1
                for m in matches
                if m.get("vulnerability", {}).get("severity", "").lower() == "critical"
            )

            # Avisar si la DB de Grype parece vacía o muy desactualizada
            db_status = grype_data.get("descriptor", {}).get("db", {})
            db_built = db_status.get("built", "")
            if db_built:
                logger.debug(f"[{repo.full_name}] Grype DB built: {db_built}")
            if findings_count == 0 and db_built == "":
                logger.warning(
                    f"[{repo.full_name}] Grype: 0 hallazgos y sin info de DB — "
                    "puede que la base de vulnerabilidades no esté inicializada. "
                    "Ejecuta: grype db update"
                )

        except json.JSONDecodeError as exc:
            return StageResult(
                repo_id=repo_id_value,
                repo_full_name=repo.full_name,
                stage="grype",
                success=False,
                duration_s=duration,
                error=f"Reporte Grype no es JSON válido: {exc}",
            )

        logger.info(
            f"[{repo.full_name}] Grype: {findings_count} vulnerabilidades "
            f"({critical_count} críticas) en {duration:.1f}s"
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
                "db_built": db_built,
            },
        )

    except Exception as e:
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="grype",
            success=False,
            error=str(e),
        )
