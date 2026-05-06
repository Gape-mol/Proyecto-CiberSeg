# Guía de Ejecución — Security Analysis Pipeline

Instrucciones paso a paso para correr el sistema completo desde cero.

---

## Requisitos previos

| Herramienta | Versión mínima | Verificar |
|---|---|---|
| Docker Desktop | 24.x | `docker --version` |
| Docker Compose | 2.x (plugin) | `docker compose version` |
| VS Code *(solo opción A)* | cualquiera | — |
| Extensión Dev Containers *(solo opción A)* | cualquiera | — |
| Git | cualquiera | `git --version` |

Necesitás también un **GitHub Personal Access Token (PAT)** con los scopes:
- `read:org` — leer la organización
- `public_repo` — clonar repositorios públicos (agregar `repo` para privados)

---

## Opción A — Dev Container en VS Code *(recomendada)*

El Dev Container instala automáticamente todas las herramientas (Python, Node.js,
CodeQL, Syft, Grype, Gitleaks) y configura el entorno sin pasos manuales.

### Paso 1 — Clonar el repositorio

```bash
git clone <url-del-repo>
cd Proyecto-CiberSeg
```

### Paso 2 — Abrir en VS Code

```bash
code .
```

VS Code detecta la carpeta `.devcontainer/` y muestra una notificación en la esquina
inferior derecha: **"Reopen in Container"**. Hacé clic en ese botón.

> Si no aparece la notificación: `Ctrl+Shift+P` → "Dev Containers: Reopen in Container"

La primera vez tarda varios minutos (descarga la imagen base y las herramientas de seguridad).
Los builds siguientes usan caché y son mucho más rápidos.

### Paso 3 — Configurar credenciales

Al terminar el build, abrí una terminal dentro del container (`Ctrl+ñ` en VS Code).
`post-create.sh` ya copió `.env.example` a `.env` automáticamente:

```bash
nano /workspace/.env
```

Completá los dos campos requeridos:

```
GITHUB_TOKEN=ghp_tu_token_aqui
GITHUB_ORG=nombre-de-la-org-aidev
```

Guardá con `Ctrl+O`, `Enter`, `Ctrl+X`.

### Paso 4 — Ejecutar el Miner

```bash
cd /workspace

# Preview: ver qué repos se procesarán sin clonar nada
python -m miner --dry-run

# Ejecución completa (clona + analiza)
python -m miner

# Con logging detallado para ver el progreso etapa por etapa
python -m miner -v
```

El miner muestra el progreso en tiempo real. Al finalizar imprime un resumen con
la cantidad de repos procesados y hallazgos por herramienta.

### Paso 5 — Abrir el Visualizer

```bash
# En otra terminal dentro del container
python /workspace/data-visualizer/serve.py
```

Abrí el navegador en **http://localhost:4173**

> El Dev Container reenvía el puerto 4173 automáticamente. VS Code muestra
> una notificación cuando el puerto está disponible.
>
> `serve.py` actúa como proxy: sirve `index.html` desde `data-visualizer/`
> y las peticiones a `/data/` las resuelve contra `/data/secpipeline.json`.

El dashboard se actualiza automáticamente cada 2 segundos mientras el miner corre.

### Paso 6 — Ejecutar los Notebooks

```bash
cd /workspace
jupyter lab --ip=0.0.0.0 --no-browser --allow-root
```

Copiá la URL que aparece en la terminal (con el token) y abrila en el navegador.
Los notebooks están en `analyzers/`:

| Notebook | Descripción |
|---|---|
| `00_overview.ipynb` | Resumen general y ranking de riesgo |
| `01_codeql.ipynb` | Análisis de vulnerabilidades estáticas |
| `02_grype.ipynb` | Análisis de CVEs en dependencias |
| `03_sbom.ipynb` | Inventario de componentes SBOM |
| `04_gitleaks.ipynb` | Análisis de secretos expuestos |

Ejecutá cada notebook con `Kernel → Restart & Run All`.

---

## Opción B — Docker Compose *(sin VS Code)*

### Paso 1 — Clonar y configurar

```bash
git clone <url-del-repo>
cd Proyecto-CiberSeg

cp .env.example .env
```

Editá `.env` con tu editor preferido:

```
GITHUB_TOKEN=ghp_tu_token_aqui
GITHUB_ORG=nombre-de-la-org-aidev
```

### Paso 2 — Ejecutar el Miner

```bash
# Construir la imagen (solo la primera vez)
docker compose build miner

# Ejecutar el pipeline completo
docker compose run --rm miner

# Con logging detallado
docker compose run --rm miner python -m miner -v

# Dry-run (solo lista repos)
docker compose run --rm miner python -m miner --dry-run
```

### Paso 3 — Abrir el Visualizer

```bash
docker compose up visualizer
```

Abrí **http://localhost:4173** en el navegador.

> En Docker Compose el volumen `dataset_data` se monta en `/app/data/` dentro del
> directorio que sirve el HTTP server, por lo que el dashboard encuentra
> `secpipeline.json` directamente sin necesitar `serve.py`.

### Paso 4 — Notebooks (requiere Python local)

Si tenés Python 3.11+ instalado localmente:

```bash
cd analyzers
pip install -r requirements.txt
jupyter lab
```

---

## Opciones del Miner

```bash
# Limitar la cantidad de repositorios (útil para pruebas)
python -m miner --limit 5

# Cambiar la organización sin editar .env
python -m miner --org otra-org

# Override de org desde CLI
python -m miner --org otra-org

# Modo continuo: repite el pipeline cada N segundos
python -m miner --continuous --interval 300

# Solo clonar los últimos commits (más rápido, sin historial completo para Gitleaks)
python -m miner --depth 1

# Guardar el resumen de la ejecución en un archivo JSON
python -m miner --output-json /data/resumen.json

# Borrar todos los datos generados y empezar de cero
python -m miner --reset

# Borrar datos y relanzar el pipeline en el mismo comando
python -m miner --reset --limit 5 -v

# Ver todas las opciones disponibles
python -m miner --help
```

---

## Variables de entorno disponibles

Configuradas en `.env` (o exportadas en la shell):

| Variable | Descripción | Default |
|---|---|---|
| `GITHUB_TOKEN` | PAT de GitHub (también acepta `GH_TOKEN`) | **requerido** |
| `GITHUB_ORG` | Slug de la organización AIDev | **requerido** |
| `DB_PATH` | Ruta al archivo JSON de salida | `/data/secpipeline.json` |
| `CLONE_ROOT` | Directorio para repos clonados | `/data/repos` |
| `REPORTS_ROOT` | Directorio para reportes SARIF/JSON | `/data/reports` |
| `REPO_LIMIT` | Máximo de repos a procesar | `50` |
| `REPO_RECENT_DAYS` | Solo repos con actividad en los últimos N días | `30` |
| `CLONE_WORKERS` | Sin efecto en modo secuencial por repo | `5` |
| `GITLEAKS_WORKERS` | Sin efecto en modo secuencial por repo | `2` |
| `SBOM_WORKERS` | Sin efecto en modo secuencial por repo | `2` |
| `GRYPE_WORKERS` | Sin efecto en modo secuencial por repo | `2` |
| `CODEQL_WORKERS` | Sin efecto en modo secuencial por repo | `1` |
| `CLONE_DEPTH` | Profundidad del clone (`none` = historial completo) | `none` |
| `SKIP_ARCHIVED` | Ignorar repos archivados | `false` |
| `REPO_VISIBILITY` | `all`, `public`, `private`, `internal` | `all` |
| `RUN_CONTINUOUS` | Activar modo continuo | `false` |
| `RUN_INTERVAL_SECONDS` | Segundos entre corridas continuas | `3600` |

---

## Empezar de cero (reset)

Para borrar todos los datos generados y hacer una extracción limpia:

```bash
# Borra dataset + repos clonados + reportes, luego sale
python -m miner --reset

# Borra todo y lanza el pipeline inmediatamente
python -m miner --reset --limit 5 -v
```

El comando elimina:
- `/data/secpipeline.json` — el dataset principal
- `/data/repos/` — todos los repositorios clonados
- `/data/reports/` — todos los reportes (Gitleaks, SBOM, Grype, CodeQL)

---

## Verificar que las herramientas están instaladas

Dentro del Dev Container o del contenedor Docker:

```bash
python   --version    # Python 3.12.x
git      --version    # 2.x.x
codeql   version      # CodeQL CLI 2.17.3
syft     version      # syft 1.4.1
grype    version      # grype 0.78.0
gitleaks version      # gitleaks v8.18.4
```

---

## Correr los tests del Miner

```bash
cd /workspace/miner
pytest tests/ -v

# Con reporte de cobertura
pytest tests/ -v --cov=miner --cov-report=term-missing
```

---

## Dónde están los datos generados
python -m miner --reset
Después de correr el miner, los datos se encuentran en:

```
/data/
├── secpipeline.json          ← dataset principal (leído por Analyzer y Visualizer)
├── repos/
│   └── <org>/
│       └── <repo>/           ← repositorios clonados
└── reports/
    └── <repo>/
        ├── gitleaks/
        │   └── <repo>-gitleaks.json
        ├── sbom/
        │   └── <repo>-sbom.cdx.json
        ├── grype/
        │   └── <repo>-grype.json
        └── codeql/
            ├── <repo>-codeql-db/   ← base de datos CodeQL (directorio)
            └── <repo>-codeql.sarif ← resultados en formato SARIF
```

En Docker Compose, estos directorios viven en volúmenes nombrados Docker:
- `repos_data` → `/data/repos`
- `reports_data` → `/data/reports`
- `dataset_data` → `/data`

Para inspeccionar el dataset directamente:

```bash
# Resumen rápido con Python
python3 -c "
import json
db = json.load(open('/data/secpipeline.json'))
cols = ['repositories','codeql_findings','grype_findings','gitleaks_findings','sbom_components']
for k in cols:
    print(f'{k}: {len(db.get(k, []))}')
"
```

---

## Flujo completo resumido

```
git clone → cp .env.example .env → editar .env
        ↓
  [Dev Container / Docker]
        ↓
  python -m miner -v          ← extrae y analiza repos
        ↓
  /data/secpipeline.json      ← dataset generado
        ↓
  ┌──────────────────────┐    ┌─────────────────────────────────┐
  │  jupyter lab         │    │  python data-visualizer/serve.py│
  │  analyzers/*.ipynb   │    │  (Dev Container)                │
  │  (análisis profundo) │    │  ó docker compose up visualizer │
  └──────────────────────┘    │  localhost:4173                  │
                              └─────────────────────────────────┘
```
