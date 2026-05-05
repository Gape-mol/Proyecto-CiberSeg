#!/usr/bin/env bash
# Levanta los 3 servicios dentro del Dev Container.
# Uso: bash /workspace/start-all.sh [--limit N] [-v] [cualquier flag de miner]
#
# Visualizer → http://localhost:4173
# Jupyter    → http://localhost:8888
# Miner      → foreground; al terminar muestra resumen y mantiene los servicios vivos

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_PATH="/data/secpipeline.json"

cleanup() {
  echo ""
  echo "Deteniendo servicios..."
  kill "$VISUALIZER_PID" "$JUPYTER_PID" 2>/dev/null || true
  wait "$VISUALIZER_PID" "$JUPYTER_PID" 2>/dev/null || true
  echo "Listo."
}
trap cleanup EXIT INT TERM

echo "=== Security Pipeline — inicio completo ==="
echo ""

# Visualizer
DATA_ROOT=/data python "$SCRIPT_DIR/data-visualizer/serve.py" &
VISUALIZER_PID=$!
echo "[visualizer] PID=$VISUALIZER_PID → http://localhost:4173"

# Jupyter Lab
jupyter lab \
  --ip=0.0.0.0 \
  --no-browser \
  --allow-root \
  --port=8888 \
  --notebook-dir="$SCRIPT_DIR/analyzers" \
  --ServerApp.token='' \
  --ServerApp.password='' \
  2>&1 | grep --line-buffered -E "(http://|ERROR)" &
JUPYTER_PID=$!
echo "[jupyter]    PID=$JUPYTER_PID → http://localhost:8888"

echo ""
echo "Esperando 2 s para que los servicios arranquen..."
sleep 2

echo ""
echo "=== Iniciando Miner ==="
set +e
python -m miner "$@"
MINER_EXIT=$?
set -e

# ── Resumen al terminar ────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          PIPELINE COMPLETADO — RESUMEN               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

python3 - <<'PYEOF'
import json, sys
from pathlib import Path

path = Path('/data/secpipeline.json')
if not path.exists():
    print("  No se encontró secpipeline.json")
    sys.exit(0)

db = json.loads(path.read_text())
repos     = db.get('repositories', [])
codeql    = db.get('codeql_findings', [])
grype     = db.get('grype_findings', [])
gitleaks  = db.get('gitleaks_findings', [])
sbom      = db.get('sbom_components', [])

cloned    = [r for r in repos if r.get('miner_status') == 'cloned']
errors    = [r for r in repos if r.get('miner_status') == 'error']
org       = db.get('organizations', [{}])[0].get('name', '?')

sev_c = lambda arr, s: sum(1 for f in arr if (f.get('severity') or '').lower() == s)

print(f"  Organización            : {org}")
print(f"  Repositorios            : {len(cloned)} analizados / {len(repos)} totales"
      + (f"  ({len(errors)} con error)" if errors else ""))
print()
print(f"  CodeQL (código fuente)  : {len(codeql):>6} hallazgos"
      f"   · {sev_c(codeql,'high')} altos · {sev_c(codeql,'medium')} medios")
print(f"  Grype  (CVEs deps)      : {len(grype):>6} hallazgos"
      f"   · {sev_c(grype,'critical')} críticos · {sev_c(grype,'high')} altos")
print(f"  Gitleaks (secretos)     : {len(gitleaks):>6} hallazgos"
      f"   · {len(set(f.get('repo_id') for f in gitleaks))} repos afectados")
print(f"  SBOM (componentes)      : {len(sbom):>6} componentes"
      f"   · {len(set(c.get('ecosystem') for c in sbom if c.get('ecosystem')))} ecosistemas")
print()

# Risk score
SEV = {'critical': 10, 'high': 5, 'medium': 2, 'low': 1}
repo_names = {r['id']: r.get('full_name', r.get('name', '?')) for r in repos}
scores = {}
for f in codeql + grype:
    rid = f.get('repo_id')
    if rid is not None:
        scores[rid] = scores.get(rid, 0) + SEV.get((f.get('severity') or '').lower(), 0)
for f in gitleaks:
    rid = f.get('repo_id')
    if rid is not None:
        scores[rid] = scores.get(rid, 0) + 3

if scores:
    print("  Top 5 repositorios por riesgo:")
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
    for rid, score in top:
        name = repo_names.get(rid, f'repo#{rid}')
        bar = '█' * min(score // 10, 20)
        print(f"    {score:>6}  {bar}  {name}")
    print()
PYEOF

echo ""
echo "  Los servicios siguen activos. Presioná Ctrl+C para detenerlos."
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  Visualizer → http://localhost:4173          │"
echo "  │  Jupyter    → http://localhost:8888          │"
echo "  └─────────────────────────────────────────────┘"
echo ""

# Mantener vivo hasta Ctrl+C
while true; do sleep 86400; done
