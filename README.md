# Security Analysis Pipeline

Pipeline de análisis de vulnerabilidades sobre organizaciones del dataset AIDev.
El sistema extrae repositorios, los analiza con herramientas de seguridad y persiste
los resultados en un dataset JSON estructurado.

## Estado actual del proyecto

| Componente  | Estado | Descripción |
|-------------|--------|-------------|
| **Miner**   | ✅ Implementado | Clona repos, ejecuta CodeQL, Syft, Grype y Gitleaks |
| **Analyzer**| 🚧 Pendiente | Notebooks de análisis exploratorio |
| **Visualizer** | 🚧 Pendiente | Dashboard web de resultados |

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                      Security Pipeline                          │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────────────┐ │
│  │  GitHub  │───▶│    Miner     │───▶│   /data/               │ │
│  │   API    │    │              │    │   ├── repos/            │ │
│  └──────────┘    │  ┌────────┐  │    │   ├── reports/         │ │
│                  │  │Gitleaks│  │    │   └── secpipeline.json  │ │
│                  │  │  Syft  │  │    └────────────┬───────────┘ │
│                  │  │  Grype │  │                 │             │
│                  │  │ CodeQL │  │                 ▼             │
│                  │  └────────┘  │    ┌────────────────────────┐ │
│                  └──────────────┘    │   Analyzer (notebooks) │ │
│                                      └────────────┬───────────┘ │
│                                                   │             │
│                                                   ▼             │
│                                      ┌────────────────────────┐ │
│                                      │  Visualizer (dashboard) │ │
│                                      └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Inicio rápido

### Opción A — Dev Container (recomendado)

Requiere [VS Code](https://code.visualstudio.com/) con la extensión
[Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
y Docker Desktop.

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd Proyecto-CiberSeg

# 2. Abrir en VS Code y abrir en Dev Container
code .
# VS Code detecta automáticamente .devcontainer/ y ofrece "Reopen in Container"
```

El container instala automáticamente todas las dependencias (Python, CodeQL, Syft, Grype,
Gitleaks) y ejecuta `post-create.sh`.

```bash
# 3. Dentro del container: configurar credenciales
nano /workspace/.env
#   GITHUB_TOKEN=ghp_tu_token_aqui
#   GITHUB_ORG=nombre-de-la-org-aidev

# 4. Ejecutar el miner
cd /workspace
python -m miner
```

### Opción B — Docker Compose

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd Proyecto-CiberSeg

# 2. Configurar credenciales
cp .env.example .env
# Editar .env con GITHUB_TOKEN y GITHUB_ORG

# 3. Ejecutar el miner
docker compose run --rm miner

# 4. (Opcional) Levantar el visualizer
docker compose up visualizer
# Acceder en http://localhost:4173
```

### Opción C — Local (requiere herramientas instaladas)

Requiere Python ≥ 3.11, git, [Gitleaks](https://github.com/gitleaks/gitleaks),
[Syft](https://github.com/anchore/syft), [Grype](https://github.com/anchore/grype)
y [CodeQL CLI](https://github.com/github/codeql-action/releases) en el `PATH`.

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd Proyecto-CiberSeg

# 2. Instalar dependencias Python
cd miner
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..

# 3. Configurar credenciales
cp .env.example .env
# Editar .env con GITHUB_TOKEN y GITHUB_ORG

# 4. Ejecutar el miner
python -m miner
```

## Configuración

Las variables se definen en `.env` (copiado desde `.env.example`):

| Variable | Descripción | Default |
|---|---|---|
| `GITHUB_TOKEN` | PAT de GitHub (scopes: `read:org`, `repo`) | **requerido** |
| `GITHUB_ORG` | Slug de la organización del dataset AIDev | **requerido** |
| `DB_PATH` | Ruta al dataset JSON | `/data/secpipeline.json` |
| `CLONE_ROOT` | Directorio raíz para repos clonados | `/data/repos` |
| `REPORTS_ROOT` | Directorio para reportes JSON/SARIF | `/data/reports` |
| `CLONE_WORKERS` | Repos clonados en paralelo | `5` |
| `CODEQL_WORKERS` | Análisis CodeQL en paralelo | `1` |
| `REPO_VISIBILITY` | `all`, `public`, `private`, `internal` | `all` |
| `SKIP_ARCHIVED` | Ignorar repos archivados | `false` |
| `CLONE_DEPTH` | Profundidad del clone (`none` = completo) | `none` |
| `REPO_LIMIT` | Máximo de repos a procesar | `50` |
| `REPO_RECENT_DAYS` | Solo repos con actividad en los últimos N días | `30` |

### Token de GitHub

El token necesita los siguientes scopes:

| Tipo de repos | Scope necesario |
|---|---|
| Solo públicos | `public_repo` |
| Privados | `repo` |
| Leer organización | `read:org` |

## Uso del Miner

```bash
# Listar repos sin clonar (modo preview)
python -m miner --dry-run

# Ejecutar el pipeline completo (lee config de .env)
python -m miner

# Override de org y workers desde CLI
python -m miner --org nombre-org --workers 10

# Limitar cantidad de repos
python -m miner --limit 10

# Logging detallado
python -m miner -v

# Modo continuo (repite el pipeline cada 10 minutos)
python -m miner --continuous --interval 600

# Guardar resumen en JSON
python -m miner --output-json /tmp/resumen.json
```

## Estructura del proyecto

```
Proyecto-CiberSeg/
├── .devcontainer/
│   ├── Dockerfile           # Imagen del devcontainer con todas las herramientas
│   ├── devcontainer.json    # Configuración VS Code Dev Container
│   └── post-create.sh       # Setup automático al crear el container
├── miner/
│   ├── miner/
│   │   ├── __main__.py      # CLI entrypoint
│   │   ├── miner.py         # GitHubClient + GitHubMiner (extracción de repos)
│   │   ├── pipeline.py      # Pipeline multi-etapa: clone→gitleaks→sbom→grype→codeql
│   │   ├── db.py            # Persistencia JSON (dataset estructurado)
│   │   └── models.py        # Dataclasses: Organization, Repository
│   ├── tests/
│   │   ├── test_miner.py
│   │   ├── test_db.py
│   │   └── test_pipeline.py
│   └── pyproject.toml
├── analyzers/               # Notebooks de análisis (pendiente)
├── data-visualizer/         # Dashboard web (pendiente)
├── docker-compose.yml
├── Dockerfile.miner
├── .env.example             # Plantilla de variables de entorno
└── README.md
```

## Dataset de salida

El miner produce `/data/secpipeline.json` con las siguientes colecciones:

| Colección | Contenido |
|---|---|
| `organizations` | Metadata de la organización |
| `repositories` | Repos seleccionados y su estado |
| `codeql_findings` | Vulnerabilidades estáticas (tipo, ubicación, severidad) |
| `grype_findings` | CVEs en dependencias (ID, paquete, severidad) |
| `sbom_components` | Componentes del SBOM generado por Syft |
| `gitleaks_findings` | Secretos detectados en el historial de commits |
| `pipeline_runs` | Historial de ejecuciones del pipeline |

## Tests

```bash
# Desde el directorio raíz del proyecto
cd miner
pytest tests/ -v

# Con reporte de cobertura
pytest tests/ -v --cov=miner --cov-report=term-missing
```

## Herramientas de análisis incluidas

| Herramienta | Versión | Propósito |
|---|---|---|
| [Gitleaks](https://github.com/gitleaks/gitleaks) | v8.18.4 | Detección de secretos en commits |
| [Syft](https://github.com/anchore/syft) | v1.4.1 | Generación de SBOM (CycloneDX) |
| [Grype](https://github.com/anchore/grype) | v0.78.0 | Detección de CVEs en dependencias |
| [CodeQL](https://codeql.github.com/) | v2.17.3 | Análisis estático de código fuente |
