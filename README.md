# Security Analysis Pipeline

Pipeline de análisis de vulnerabilidades sobre organizaciones del dataset AIDev.
El sistema extrae repositorios, los analiza con cuatro herramientas de seguridad y persiste
los resultados en un dataset JSON estructurado.

## Estado actual del proyecto

| Componente  | Estado | Descripción |
|-------------|--------|-------------|
| **Miner**      | ✅ Implementado | Pipeline async: clone → Gitleaks → Syft → Grype → CodeQL |
| **Analyzer**   | ✅ Implementado | 5 notebooks: overview, CodeQL, Grype, SBOM, Gitleaks |
| **Visualizer** | ✅ Implementado | Dashboard HTML/JS con auto-refresh cada 2 s |

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

# 5. (Opcional) Levantar el visualizer — usa serve.py para proxear /data/
python /workspace/data-visualizer/serve.py
# Acceder en http://localhost:4173
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

> En Docker Compose el visualizer usa `python -m http.server` directo: el volumen
> `dataset_data` se monta en `/app/data/`, dentro del directorio servido, por lo que
> no necesita el script `serve.py`.

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

Las variables se definen en `.env` (copiado desde `.env.example`).
Solo `GITHUB_TOKEN` y `GITHUB_ORG` son obligatorias; el resto tiene defaults razonables.

| Variable | Descripción | Default |
|---|---|---|
| `GITHUB_TOKEN` | PAT de GitHub (o `GH_TOKEN`) | **requerido** |
| `GITHUB_ORG` | Slug de la organización del dataset AIDev | **requerido** |
| `DB_PATH` | Ruta al dataset JSON | `/data/secpipeline.json` |
| `CLONE_ROOT` | Directorio raíz para repos clonados | `/data/repos` |
| `REPORTS_ROOT` | Directorio para reportes JSON/SARIF | `/data/reports` |
| `CLONE_WORKERS` | Repos clonados en paralelo | `5` |
| `GITLEAKS_WORKERS` | Workers de Gitleaks en paralelo | `2` |
| `SBOM_WORKERS` | Workers de Syft en paralelo | `2` |
| `GRYPE_WORKERS` | Workers de Grype en paralelo | `2` |
| `CODEQL_WORKERS` | Workers de CodeQL en paralelo (CPU-intensivo) | `1` |
| `CLONE_DEPTH` | Profundidad del clone (`none` = historial completo) | `none` |
| `REPO_LIMIT` | Máximo de repos a procesar | `50` |
| `REPO_RECENT_DAYS` | Solo repos con actividad en los últimos N días | `30` |
| `REPO_VISIBILITY` | `all`, `public`, `private`, `internal` | `all` |
| `SKIP_ARCHIVED` | Ignorar repos archivados | `false` |
| `RUN_CONTINUOUS` | Activar modo continuo (`true`/`false`) | `false` |
| `RUN_INTERVAL_SECONDS` | Segundos entre corridas en modo continuo | `3600` |

### Token de GitHub

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

# Borrar todos los datos y empezar de cero
python -m miner --reset

# Borrar datos y lanzar una nueva extracción en el mismo comando
python -m miner --reset --limit 5 -v
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
│   │   ├── __main__.py      # CLI entrypoint y orquestación
│   │   ├── miner.py         # GitHubClient + GitHubMiner (extracción de repos)
│   │   ├── pipeline.py      # Pipeline multi-etapa: clone→gitleaks→sbom→grype→codeql
│   │   ├── db.py            # Persistencia JSON (dataset estructurado)
│   │   └── models.py        # Dataclasses: Organization, Repository
│   ├── tests/
│   │   ├── test_miner.py
│   │   ├── test_db.py
│   │   └── test_pipeline.py
│   └── pyproject.toml
├── analyzers/
│   ├── 00_overview.ipynb    # Resumen general + puntuación de riesgo
│   ├── 01_codeql.ipynb      # Análisis estático (reglas, CWEs, archivos)
│   ├── 02_grype.ipynb       # CVEs en dependencias (CVSS, remediabilidad)
│   ├── 03_sbom.ipynb        # Componentes SBOM (ecosistemas, licencias)
│   ├── 04_gitleaks.ipynb    # Secretos expuestos (tipos, autores, timeline)
│   └── requirements.txt
├── data-visualizer/
│   ├── index.html           # Dashboard HTML/JS con auto-refresh cada 2 s
│   └── serve.py             # Servidor HTTP con proxy para /data/ (Dev Container)
├── docker-compose.yml
├── docker-compose.override.yml  # Overrides para Dev Container
├── Dockerfile.miner
├── .env.example             # Plantilla de variables de entorno
├── README.md
└── EJECUCION.md             # Guía paso a paso para correr el sistema
```

## Dataset de salida (`secpipeline.json`)

El miner produce `/data/secpipeline.json` con las siguientes colecciones:

| Colección | Contenido |
|---|---|
| `organizations` | Metadata de la organización |
| `repositories` | Repos seleccionados, rutas de clone y estado del pipeline |
| `gitleaks_scans` | Registro de cada escaneo de Gitleaks (repo, timestamp, estado) |
| `gitleaks_findings` | Secretos detectados (tipo, archivo, línea, autor, commit) |
| `sbom_scans` | Registro de cada generación de SBOM con Syft |
| `sbom_components` | Componentes del SBOM (nombre, versión, purl, licencia, ecosistema) |
| `grype_scans` | Registro de cada escaneo de Grype |
| `grype_findings` | CVEs en dependencias (ID, paquete, severidad, CVSS, fix) |
| `codeql_scans` | Registro de cada análisis CodeQL (lenguaje, estado) |
| `codeql_findings` | Vulnerabilidades estáticas (regla, CWE, archivo, línea, severidad) |
| `pipeline_runs` | Reservado para historial de ejecuciones (actualmente sin uso) |

## Decisiones de Diseño

### 1. JSON como contrato de datos entre componentes

Se eligió un único archivo JSON (`secpipeline.json`) como mecanismo de intercambio entre el Miner, el Analyzer y el Visualizer, en lugar de una base de datos relacional o una API. Esto elimina dependencias de infraestructura (no se necesita un servidor de base de datos) y hace que el dataset sea directamente inspeccionable, versionable y portable. El archivo se comparte entre servicios mediante un Docker volume nombrado (`dataset_data`), lo que mantiene el desacoplamiento sin acoplamiento de red.

### 2. Pipeline async por etapas con workers paralelos

El Miner implementa un pipeline de cinco etapas secuenciales (clone → Gitleaks → SBOM → Grype → CodeQL) donde cada etapa procesa múltiples repositorios en paralelo mediante `asyncio.Queue` y workers configurables. La secuencialidad entre etapas garantiza que Grype solo corra sobre un SBOM ya generado, y que CodeQL solo corra sobre un repo ya clonado. Esta arquitectura permite escalar cada etapa de forma independiente.

### 3. Selección de repos por actividad reciente y popularidad

El miner trae hasta `REPO_LIMIT × 4` repos ordenados por actividad (push reciente) y filtra por `REPO_RECENT_DAYS`. Si hay suficientes repos recientes, los ordena por estrellas; si no, completa con los más populares del resto de la org. Esto garantiza analizar repos relevantes sin consumir el límite de 50 en repos abandonados.

### 4. Visualizer como HTML estático sin build

El dashboard se implementó como un único `index.html` con JavaScript puro (ES6+) y Chart.js desde CDN, sin herramientas de build. En el Dev Container se sirve con `serve.py`, que actúa como proxy para las peticiones a `/data/` (los archivos de datos están en `/data`, fuera del directorio del visualizer). En Docker Compose el volumen de datos se monta directamente dentro del directorio servido, por lo que alcanza con `python -m http.server`.

### 5. Gitleaks como herramienta adicional al enunciado

El enunciado especifica CodeQL, Syft y Grype. Se incorporó Gitleaks porque los repositorios frecuentemente contienen secretos expuestos (tokens, API keys) que no se detectan con análisis estático ni con escaneo de dependencias. El análisis de secretos aporta una dimensión de riesgo complementaria.

### 6. Puntuación de riesgo ponderada

Score compuesto para comparar repositorios: `Critical×10 + High×5 + Medium×2 + Low×1 + Secreto×3`. Los pesos reflejan el impacto potencial según las escalas CVSS, con un factor fijo para secretos (no tienen severidad CVSS normalizada).

## Tests

```bash
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
