from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from ..models import Repository
from .types import StageResult, repo_id

logger = logging.getLogger(__name__)

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

_CODEQL_NO_BUILD = {"javascript", "python", "ruby"}


# Runs CodeQL analysis for supported languages and returns a stage result.
async def stage_codeql(
    repo: Repository,
    clone_path: Path,
    output_dir: Path,
    timeout: int = 1800,
) -> StageResult:
    repo_id_value = repo_id(repo)
    if not shutil.which("codeql"):
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=False,
            error="codeql no encontrado en PATH. Instala: https://github.com/github/codeql-action",
        )

    codeql_lang = CODEQL_LANGUAGE_MAP.get(repo.language or "")
    if not codeql_lang:
        logger.info(
            f"[{repo.full_name}] CodeQL: lenguaje '{repo.language}' no soportado, saltando."
        )
        return StageResult(
            repo_id=repo_id_value,
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
        create_cmd = [
            "codeql",
            "database",
            "create",
            str(db_path),
            "--language",
            codeql_lang,
            "--source-root",
            str(clone_path),
            "--overwrite",
            "--quiet",
        ]
        if codeql_lang in _CODEQL_NO_BUILD:
            create_cmd += ["--build-mode", "none"]

        logger.info(f"[{repo.full_name}] CodeQL [{codeql_lang}] — creando base de datos…")
        proc = await asyncio.create_subprocess_exec(
            *create_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        t_create = asyncio.get_event_loop().time() - t0

        if proc.returncode != 0:
            return StageResult(
                repo_id=repo_id_value,
                repo_full_name=repo.full_name,
                stage="codeql",
                success=False,
                error=f"codeql database create fallo: {stderr.decode().strip()[:500]}",
            )

        logger.info(
            f"[{repo.full_name}] CodeQL [{codeql_lang}] — "
            f"base de datos lista ({t_create:.0f}s) → analizando…"
        )
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
        _, stderr = await proc.communicate()
        duration = asyncio.get_event_loop().time() - t0

        if proc.returncode != 0:
            return StageResult(
                repo_id=repo_id_value,
                repo_full_name=repo.full_name,
                stage="codeql",
                success=False,
                duration_s=duration,
                error=f"codeql analyze fallo: {stderr.decode().strip()[:500]}",
            )

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
            repo_id=repo_id_value,
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

    except Exception as e:
        return StageResult(
            repo_id=repo_id_value,
            repo_full_name=repo.full_name,
            stage="codeql",
            success=False,
            error=str(e),
        )
