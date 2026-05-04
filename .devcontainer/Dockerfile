# =============================================================
# Security Pipeline — Devcontainer
# =============================================================
# Imagen base: Python 3.12 slim (Debian Bookworm)
# Incluye: git, gitleaks, syft, grype, codeql, node.js, python
# =============================================================

FROM python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

# Versiones de herramientas — actualizar aquí para upgrades
ARG GITLEAKS_VERSION=8.18.4
ARG SYFT_VERSION=1.4.1
ARG GRYPE_VERSION=0.78.0
ARG CODEQL_VERSION=2.17.3

# -------------------------------------------------------------
# Sistema base
# -------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Necesario para clonar repos
    git \
    # Herramientas de red y descarga
    curl \
    wget \
    ca-certificates \
    # Para descomprimir los binarios de las herramientas
    unzip \
    tar \
    # CodeQL necesita java para algunos lenguajes
    default-jre-headless \
    # Utilidades de desarrollo
    bash-completion \
    jq \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------
# Node.js 20 LTS — runtime JavaScript (visualizer + tooling)
# https://nodejs.org
# -------------------------------------------------------------
ARG NODE_MAJOR=20
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version \
    && npm --version

# -------------------------------------------------------------
# Usuario no-root (recomendado por devcontainer spec)
# -------------------------------------------------------------
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && mkdir -p /data/repos /data/reports \
    && chown -R $USERNAME:$USERNAME /data

# -------------------------------------------------------------
# Gitleaks — detección de secretos en repositorios
# https://github.com/gitleaks/gitleaks
# -------------------------------------------------------------
RUN curl -sSfL \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    | tar -xz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && gitleaks version

# -------------------------------------------------------------
# Syft — generación de SBOM
# https://github.com/anchore/syft
# -------------------------------------------------------------
RUN curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh \
    | sh -s -- -b /usr/local/bin "v${SYFT_VERSION}" \
    && syft version

# -------------------------------------------------------------
# Grype — escaneo de vulnerabilidades en SBOM
# https://github.com/anchore/grype
# -------------------------------------------------------------
RUN curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh \
    | sh -s -- -b /usr/local/bin "v${GRYPE_VERSION}" \
    && grype version

# -------------------------------------------------------------
# CodeQL — análisis estático de código
# https://github.com/github/codeql-cli-binaries
# Nota: el bundle incluye las queries de seguridad estándar
# -------------------------------------------------------------
RUN mkdir -p /opt/codeql \
    && curl -sSfL \
    "https://github.com/github/codeql-action/releases/download/codeql-bundle-v${CODEQL_VERSION}/codeql-bundle-linux64.tar.gz" \
    | tar -xz -C /opt/codeql --strip-components=1 \
    && ln -s /opt/codeql/codeql /usr/local/bin/codeql \
    && chown -R $USERNAME:$USERNAME /opt/codeql \
    && codeql version

# -------------------------------------------------------------
# Python — dependencias del miner
# -------------------------------------------------------------
WORKDIR /workspace

# Copiar solo los archivos de dependencias primero (mejor cache)
COPY miner/pyproject.toml ./miner/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e "./miner[dev]"

COPY analyzers/requirements.txt ./analyzers/

RUN pip install --no-cache-dir -r ./analyzers/requirements.txt

# -------------------------------------------------------------
# Configuración final
# -------------------------------------------------------------

# PATH: agregar .local/bin del usuario vscode para que pip install --user
# quede accesible (evita el WARNING de github-miner no encontrado en PATH)
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Git: marcar /data como directorio seguro (repos clonados por root o bind mounts)
RUN git config --system --add safe.directory '/data/repos/*' \
    && git config --system --add safe.directory /workspace

# Shell completions para las herramientas
RUN gitleaks completion bash > /etc/bash_completion.d/gitleaks 2>/dev/null || true

USER $USERNAME

# Precalentar la DB de vulnerabilidades de Grype en el build
# (evita la descarga en el primer scan — son ~200MB)
# Comentar si el build tarda demasiado y se prefiere descargar on-demand
RUN grype db update || true

CMD ["bash"]
