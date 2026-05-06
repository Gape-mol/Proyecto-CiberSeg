from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from .miner import GitHubMiner, MinerConfig
from .pipeline import Pipeline, PipelineConfig
from .store import JsonStore

# ── ANSI helpers ───────────────────────────────────────────────────────────────
_R = "\033[0m"  # reset
_B = "\033[1m"  # bold
_D = "\033[2m"  # dim

# Stage badge colors
_STAGE_COLOR: dict[str, str] = {
    "clone": "\033[94m",  # azul claro
    "gitleaks": "\033[91m",  # rojo claro
    "sbom": "\033[95m",  # magenta claro
    "grype": "\033[93m",  # amarillo claro
    "codeql": "\033[92m",  # verde claro
}

# Logger-name colors (cuando no hay stage detectado)
_LOGGER_COLOR: dict[str, str] = {
    "miner.cli": "\033[97m",  # blanco brillante
    "miner.miner": "\033[96m",  # cian claro
    "miner.store": "\033[90m",  # gris oscuro
    "miner.pipeline": "\033[97m",  # blanco brillante
}

# Level colors + símbolo
_LEVEL_FMT: dict[str, tuple[str, str]] = {
    "DEBUG": ("\033[90m", "·"),  # gris
    "INFO": ("\033[37m", "→"),  # blanco
    "WARNING": ("\033[33m", "⚠ "),  # amarillo
    "ERROR": ("\033[31m", "✗ "),  # rojo
    "CRITICAL": ("\033[41m", "!! "),  # fondo rojo
}

_STAGE_RE = re.compile(r"\[(clone|gitleaks|sbom|grype|codeql)\]", re.IGNORECASE)


class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()

        # Detectar stage desde el mensaje
        m = _STAGE_RE.search(msg)
        stage = m.group(1).lower() if m else None
        line_color = (
            _STAGE_COLOR.get(stage, "") if stage else _LOGGER_COLOR.get(record.name, "\033[37m")
        )

        # Badge
        if stage:
            badge = f"{_B}{line_color}[{stage.upper():8}]{_R}"
        else:
            short = record.name.replace("miner.", "")
            badge = f"{_D}{line_color}[{short:8}]{_R}"

        # Timestamp
        ts = f"{_D}{self.formatTime(record, self.datefmt)}{_R}"

        # Level
        lc, sym = _LEVEL_FMT.get(record.levelname, ("\033[37m", " "))
        level = f"{lc}{sym}{_R}"

        # Mensaje coloreado
        colored_msg = f"{line_color}{msg}{_R}"

        # Traceback si lo hay
        if record.exc_info:
            colored_msg += "\n" + self.formatException(record.exc_info)

        return f"{ts} {level} {badge} {colored_msg}"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GitHub Organization Miner — extrae y clona repos para análisis de seguridad",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Config completa por variables de entorno
  GITHUB_TOKEN=ghp_xxx GITHUB_ORG=mi-org python -m miner

  # Sobrescribir algunos valores por CLI
  python -m miner --org otra-org --workers 10 --depth 0

  # Solo listar repos sin clonar (dry-run)
  python -m miner --dry-run
        """,
    )
    parser.add_argument("--org", help="Nombre de la organización GitHub (override de GITHUB_ORG)")
    parser.add_argument("--workers", type=int, help="Repos a clonar en paralelo (default: 5)")
    parser.add_argument(
        "--depth", type=int, help="Profundidad del clone. 0=completo (default para gitleaks)"
    )
    parser.add_argument("--skip-archived", action="store_true", help="Ignorar repos archivados")
    parser.add_argument(
        "--visibility", choices=["all", "public", "private", "internal"], default=None
    )
    parser.add_argument(
        "--limit", type=int, help="Máximo de repos a analizar (default: REPO_LIMIT o 50)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Lista repos sin clonar ni modificar DB"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Repite el pipeline en loop hasta interrupción",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Segundos entre corridas en modo continuo (default: 3600)",
    )
    parser.add_argument("--output-json", type=Path, help="Guarda el resumen en un archivo JSON")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra el dataset, repos clonados y reportes antes de empezar (empieza de cero)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Logging detallado (DEBUG)")
    return parser.parse_args()


async def run_pipeline_once(
    config: MinerConfig,
    output_json: Path | None,
) -> int:
    logger = logging.getLogger("miner.cli")
    db = JsonStore(config.db_path)
    try:
        await db.connect()

        miner = GitHubMiner(config=config, db=db)
        miner_summary, repos = await miner.run()

        if not repos:
            logger.warning("No se encontraron repos para analizar. Abortando.")
            return 0

        reports_root = Path(os.environ.get("REPORTS_ROOT", "/data/reports"))
        pipeline_config = PipelineConfig(
            clone_root=config.clone_root,
            output_root=reports_root,
            github_token=config.github_token,
            clone_workers=config.clone_workers,
            clone_timeout=config.clone_timeout,
            clone_depth=config.clone_depth,
            gitleaks_workers=int(os.environ.get("GITLEAKS_WORKERS", "2")),
            sbom_workers=int(os.environ.get("SBOM_WORKERS", "2")),
            grype_workers=int(os.environ.get("GRYPE_WORKERS", "2")),
            codeql_workers=int(os.environ.get("CODEQL_WORKERS", "2")),
            gitleaks_timeout=int(os.environ.get("GITLEAKS_TIMEOUT", "300")),
            sbom_timeout=int(os.environ.get("SBOM_TIMEOUT", "180")),
            grype_timeout=int(os.environ.get("GRYPE_TIMEOUT", "180")),
            codeql_timeout=int(os.environ.get("CODEQL_TIMEOUT", "1800")),
        )

        pipeline = Pipeline(config=pipeline_config, db=db)
        pipeline_summary = await pipeline.run(repos)

        summary = {**miner_summary, **pipeline_summary}

        print("\n" + "=" * 55)
        print("RESUMEN DEL PIPELINE")
        print("=" * 55)
        print(f"  {'org':<22} {summary['org']}")
        print(f"  {'repos_seleccionados':<22} {summary['repos_selected']}")
        print(f"  {'timestamp':<22} {summary['timestamp']}")
        print()
        for stage, stats in summary.get("stages", {}).items():
            ok = stats["ok"]
            fail = stats["failed"]
            avg = stats["avg_duration_s"]
            print(f"  {stage:<10} ok={ok}  fail={fail}  avg={avg}s")
        print("=" * 55)

        if output_json:
            output_json.write_text(json.dumps(summary, indent=2, default=str))
            logger.info(f"Resumen guardado en: {output_json}")

        failed_stages = sum(s["failed"] for s in summary.get("stages", {}).values())
        return 0 if failed_stages == 0 else 2
    finally:
        await db.close()


async def main() -> int:
    load_dotenv()
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("miner.cli")

    try:
        config = MinerConfig.from_env()
    except OSError as e:
        logger.error(str(e))
        return 1

    if args.org:
        config.org_name = args.org
    if args.workers:
        config.clone_workers = args.workers
    if args.depth is not None:
        config.clone_depth = None if args.depth == 0 else args.depth
    if args.skip_archived:
        config.skip_archived = True
    if args.visibility:
        config.visibility = args.visibility
    if args.limit:
        config.repo_limit = args.limit
    if args.continuous:
        config.continuous = True
    if args.interval:
        config.run_interval_s = args.interval

    logger.info(
        f"Config: org={config.org_name}, workers={config.clone_workers}, "
        f"clone_root={config.clone_root}, depth={config.clone_depth or 'full'}, "
        f"repo_limit={config.repo_limit}, continuous={config.continuous}, "
        f"interval_s={config.run_interval_s}"
    )

    if args.reset:
        import shutil

        reports_root = Path(os.environ.get("REPORTS_ROOT", "/data/reports"))
        targets = [
            (Path(config.db_path), "dataset"),
            (config.clone_root, "repos clonados"),
            (reports_root, "reportes"),
        ]
        logger.warning("━" * 50)
        logger.warning("⚠  RESET — Se eliminarán los siguientes datos:")
        for path, label in targets:
            exists = path.exists()
            status = "existe" if exists else "no encontrado"
            logger.warning(f"   • {label:<20} {path}  [{status}]")
        logger.warning("━" * 50)
        for path, label in targets:
            if path.is_file():
                path.unlink()
                logger.info(f"   ✓ {label} eliminado")
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                logger.info(f"   ✓ {label} eliminado")
            else:
                logger.info(f"   - {label} no existía, omitido")
        logger.info("━" * 50)
        logger.info("✅  Reset completo — listo para una nueva extracción.")
        if not (args.dry_run or args.continuous):
            return 0

    if args.dry_run:
        if config.continuous:
            logger.error("--dry-run no es compatible con --continuous")
            return 1
        from .miner import GitHubClient

        client = GitHubClient(config.github_token)
        try:
            await client.preflight_check(config.org_name)
        except Exception as e:
            logger.error(str(e))
            return 1
        count = 0
        logger.info(f"[DRY RUN] Listando repos de '{config.org_name}'…")
        async for repo in client.list_org_repos(config.org_name, config.visibility):
            archived = " [ARCHIVED]" if repo.get("archived") else ""
            print(f"  {repo['full_name']} ({repo.get('language', '?')}){archived}")
            count += 1
        print(f"\nTotal: {count} repositorios")
        return 0

    # Preflight: validar token y org antes de empezar
    try:
        from .miner import GitHubClient

        await GitHubClient(config.github_token).preflight_check(config.org_name)
    except Exception as e:
        logger.error(str(e))
        return 1

    try:
        if not config.continuous:
            return await run_pipeline_once(config, args.output_json)

        run_number = 0
        while True:
            run_number += 1
            logger.info(f"Iniciando corrida continua #{run_number}")
            exit_code = await run_pipeline_once(config, args.output_json)
            logger.info(
                f"Corrida #{run_number} finalizada con código {exit_code}. "
                f"Esperando {config.run_interval_s}s para la próxima ejecución."
            )
            await asyncio.sleep(config.run_interval_s)

    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario.")
        return 130
    except Exception as e:
        logger.exception(f"Error fatal: {e}")
        return 1


def run() -> None:
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    run()
