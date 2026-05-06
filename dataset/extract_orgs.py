#!/usr/bin/env python3
"""
extract_orgs.py — Extrae organizaciones del dataset AIDev (Hugging Face)

Uso:
    python3 extract_orgs.py
    python3 extract_orgs.py --output empresas.csv

Requisitos:
    pip install datasets
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrae orgs del dataset AIDev de Hugging Face")
    parser.add_argument("--output", "-o", default="orgs.csv", help="CSV de salida (default: orgs.csv)")
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
        org = full_name.split("/")[0] if "/" in full_name else "unknown"
        orgs[org].append(row)

    rows = []
    for org, repos in sorted(orgs.items()):
        languages = sorted({r["language"] for r in repos if r.get("language")})
        rows.append({
            "org":         org,
            "total_repos": len(repos),
            "lenguajes":   ", ".join(languages) if languages else "—",
        })

    rows.sort(key=lambda r: r["total_repos"], reverse=True)

    out_path = Path(args.output)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["org", "total_repos", "lenguajes"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ {len(rows)} organizaciones exportadas → {out_path}")
    print(f"  Total repos en dataset: {len(ds)}")


if __name__ == "__main__":
    main()
