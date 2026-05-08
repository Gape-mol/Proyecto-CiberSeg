#!/usr/bin/env python3
"""
extract_orgs.py — Extrae organizaciones del dataset AIDev (Hugging Face)
y genera un CSV con una fila por empresa.

Con --check-github verifica qué orgs y repos siguen disponibles en GitHub.

Uso:
    python3 extract_orgs.py
    python3 extract_orgs.py --check-github
    python3 extract_orgs.py --check-github --workers 20
    python3 extract_orgs.py --output orgs.csv

Requisitos:
    pip install datasets httpx
    GITHUB_TOKEN en entorno (opcional pero evita rate limit de 60 req/h)
"""

import argparse
import asyncio
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx


GH_API = "https://api.github.com"
_CONCURRENCY = 10  # peticiones simultáneas por defecto


async def _check_org(client: httpx.AsyncClient, org: str) -> bool:
    try:
        r = await client.get(f"{GH_API}/orgs/{org}", timeout=8)
        return r.status_code == 200
    except Exception:
        return False


async def _check_repo(client: httpx.AsyncClient, full_name: str) -> bool:
    try:
        r = await client.get(f"{GH_API}/repos/{full_name}", timeout=8)
        return r.status_code == 200
    except Exception:
        return False


async def _check_all(
    orgs: dict[str, list[dict]],
    token: str | None,
    workers: int,
) -> dict[str, dict]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    sem = asyncio.Semaphore(workers)
    results: dict[str, dict] = {}

    async with httpx.AsyncClient(headers=headers) as client:

        # ── Paso 1: verificar orgs ──────────────────────────────────
        total_orgs = len(orgs)
        print(f"\n  [1/2] Verificando {total_orgs} organizaciones en GitHub…")

        async def check_org_sem(org: str) -> tuple[str, bool]:
            async with sem:
                ok = await _check_org(client, org)
                return org, ok

        org_tasks = [check_org_sem(org) for org in orgs]
        done_orgs = 0
        for coro in asyncio.as_completed(org_tasks):
            org, exists = await coro
            results[org] = {"org_exists": exists, "available_repos": 0, "checked_repos": 0}
            done_orgs += 1
            if done_orgs % 50 == 0 or done_orgs == total_orgs:
                alive = sum(1 for v in results.values() if v["org_exists"])
                print(f"    {done_orgs}/{total_orgs} orgs verificadas — {alive} disponibles")

        # ── Paso 2: verificar repos solo de orgs que existen ───────
        live_orgs = {org: repos for org, repos in orgs.items() if results[org]["org_exists"]}
        all_repos = [(org, r["full_name"]) for org, repos in live_orgs.items() for r in repos if r.get("full_name")]
        total_repos = len(all_repos)
        print(f"\n  [2/2] Verificando {total_repos} repos de orgs disponibles…")

        async def check_repo_sem(org: str, full_name: str) -> tuple[str, bool]:
            async with sem:
                ok = await _check_repo(client, full_name)
                return org, ok

        repo_tasks = [check_repo_sem(org, fn) for org, fn in all_repos]
        done_repos = 0
        for coro in asyncio.as_completed(repo_tasks):
            org, ok = await coro
            results[org]["checked_repos"] += 1
            if ok:
                results[org]["available_repos"] += 1
            done_repos += 1
            if done_repos % 100 == 0 or done_repos == total_repos:
                print(f"    {done_repos}/{total_repos} repos verificados")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrae orgs del dataset AIDev de Hugging Face")
    parser.add_argument("--output", "-o", default="orgs.csv", help="Archivo CSV de salida")
    parser.add_argument(
        "--check-github", action="store_true",
        help="Verificar disponibilidad de orgs y repos en GitHub",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=_CONCURRENCY,
        help=f"Peticiones simultáneas a GitHub (default: {_CONCURRENCY})",
    )
    args = parser.parse_args()

    try:
        from datasets import load_dataset
    except ImportError:
        print("✗ Falta la librería: pip install datasets", file=sys.stderr)
        sys.exit(1)

    print("  Descargando dataset AIDev desde Hugging Face…")
    ds = load_dataset("hao-li/AIDev", "all_repository", split="train")
    print(f"  {len(ds)} repositorios cargados.")

    orgs: dict[str, list[dict]] = defaultdict(list)
    for row in ds:
        full_name = (row.get("full_name") or "").strip()
        if "/" not in full_name:
            continue
        owner = full_name.split("/")[0]
        orgs[owner].append(dict(row))

    # ── Verificación GitHub (opcional) ─────────────────────────────
    gh_results: dict[str, dict] = {}
    if args.check_github:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            print("  ⚠ Sin GITHUB_TOKEN — rate limit: 60 req/h (muy lento con muchas orgs)")
        else:
            print("  ✓ GITHUB_TOKEN encontrado")
        gh_results = asyncio.run(_check_all(orgs, token, args.workers))

    # ── Construir filas CSV ─────────────────────────────────────────
    rows = []
    for owner, repos in sorted(orgs.items()):
        languages  = sorted({r["language"] for r in repos if r.get("language")})
        repo_names = [r["full_name"].split("/")[1] for r in repos if r.get("full_name")]
        row: dict = {
            "org":         owner,
            "total_repos": len(repos),
            "languages":   ", ".join(languages) if languages else "—",
            "repos":       ", ".join(repo_names),
        }
        if args.check_github and owner in gh_results:
            g = gh_results[owner]
            row["org_en_github"]     = "sí" if g["org_exists"] else "no"
            row["repos_disponibles"] = g["available_repos"] if g["org_exists"] else "—"
            row["repos_verificados"] = g["checked_repos"]   if g["org_exists"] else "—"
        rows.append(row)

    rows.sort(key=lambda r: r["total_repos"], reverse=True)

    fieldnames = ["org", "total_repos", "languages", "repos"]
    if args.check_github:
        fieldnames += ["org_en_github", "repos_disponibles", "repos_verificados"]

    out_path = Path(args.output)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ {len(rows)} organizaciones exportadas → {out_path}")
    if args.check_github:
        alive_orgs  = sum(1 for v in gh_results.values() if v["org_exists"])
        alive_repos = sum(v["available_repos"] for v in gh_results.values())
        checked_repos = sum(v["checked_repos"] for v in gh_results.values())
        print(f"  Orgs disponibles en GitHub: {alive_orgs}/{len(orgs)}")
        print(f"  Repos disponibles:          {alive_repos}/{checked_repos} verificados")


if __name__ == "__main__":
    main()
