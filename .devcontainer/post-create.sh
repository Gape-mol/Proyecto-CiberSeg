#!/usr/bin/env bash
# =============================================================
# post-create.sh — se ejecuta una sola vez al crear el container
# =============================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }

info "Iniciando configuración del devcontainer..."

# -------------------------------------------------------------
# 1. Copiar .env si no existe
# -------------------------------------------------------------
if [ ! -f /workspace/.env ]; then
    if [ -f /workspace/.env.example ]; then
        cp /workspace/.env.example /workspace/.env
        warn ".env creado desde .env.example — completar GITHUB_TOKEN y GITHUB_ORG"
    fi
fi

# -------------------------------------------------------------
# 2. Instalar dependencias Python en modo editable
#    (por si el pip install del Dockerfile quedó desactualizado)
# -------------------------------------------------------------
info "Instalando dependencias Python..."
pip install --quiet -e "/workspace/miner[dev]"

# -------------------------------------------------------------
# 3. Instalar dependencias del analyzer
# -------------------------------------------------------------
info "Instalando dependencias del analyzer..."
pip install --quiet -r /workspace/analyzers/requirements.txt

# -------------------------------------------------------------
# 4. Verificar que todas las herramientas estén disponibles
# -------------------------------------------------------------
info "Verificando herramientas de análisis..."
TOOLS=(git gitleaks syft grype codeql)
ALL_OK=true
for tool in "${TOOLS[@]}"; do
    if command -v "$tool" &>/dev/null; then
        VERSION=$("$tool" version 2>&1 | head -1)
        echo "  ✓ $tool — $VERSION"
    else
        echo "  ✗ $tool — NO ENCONTRADO"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    warn "Algunas herramientas no están disponibles. Rebuild del container puede ser necesario."
fi

# -------------------------------------------------------------
# 5. Crear directorios de datos si no existen
# -------------------------------------------------------------
mkdir -p /data/repos /data/reports

# -------------------------------------------------------------
# 6. Mensaje final
# -------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Security Pipeline — devcontainer listo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Comandos rápidos:"
echo "    python -m miner --dry-run    Lista repos de la org"
echo "    python -m miner              Clonar + analizar"
echo "    python /workspace/data-visualizer/serve.py"
echo "    pytest miner/tests/ -v       Correr tests"
echo ""
echo "  Configurar antes de usar:"
echo "    nano /workspace/.env         Agregar GITHUB_TOKEN y GITHUB_ORG"
echo ""
