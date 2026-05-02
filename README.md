# GitHub Organization Miner

Primer módulo del **Security Analysis Pipeline**. Extrae todos los repositorios
de una organización GitHub, persiste su metadata en PostgreSQL y los clona
localmente para que los analizadores (Gitleaks, Grype, CodeQL) puedan operar.

## Arquitectura del pipeline completo

```
┌─────────────────────────────────────────────────────────────┐
│                   Security Pipeline                         │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │  GitHub  │───▶│  Miner   │───▶│  /data/  │             │
│  │   API    │    │ (este)   │    │   repos/ │             │
│  └──────────┘    └─────┬────┘    └────┬─────┘              │
│                        │              │                     │
│                        ▼              ▼                     │
│                  ┌──────────┐   ┌──────────────────────┐   │
│                  │ PostgreSQL│   │    Analizadores       │   │
│                  │    DB    │◀──│  Gitleaks │ Grype     │   │
│                  │          │   │  SBOM     │ CodeQL    │   │
│                  └────┬─────┘   └──────────────────────┘   │
│                       │                                     │
│                       ▼                                     │
│                  ┌──────────┐                               │
│                  │ Frontend │                               │
│                  │Dashboard │                               │
│                  └──────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

## Instalación

```bash
# Clonar el repo del pipeline
git clone https://github.com/tu-org/security-pipeline
cd security-pipeline/github-miner

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -e ".[dev]"

# Configurar variables de entorno
cp config/.env.example .env
# Editar .env con tu GITHUB_TOKEN y GITHUB_ORG
```

## Configuración

Todas las opciones se configuran por variables de entorno (ver `config/.env.example`):

| Variable | Descripción | Default |
|---|---|---|
| `GITHUB_TOKEN` | PAT de GitHub (scopes: `read:org`, `repo`) | **requerido** |
| `GITHUB_ORG` | Slug de la organización | **requerido** |
| `DATABASE_URL` | DSN de PostgreSQL | `postgresql://user:pass@localhost/secpipeline` |
| `CLONE_ROOT` | Directorio raíz para repos | `/data/repos` |
| `CLONE_WORKERS` | Repos en paralelo | `5` |
| `REPO_VISIBILITY` | `all`, `public`, `private`, `internal` | `all` |
| `SKIP_ARCHIVED` | Ignorar repos archivados | `false` |
| `CLONE_DEPTH` | Profundidad del clone (`none` = completo) | `none` |
| `CLONE_TIMEOUT` | Timeout por repo en segundos | `600` |

### ⚠️ Nota sobre `CLONE_DEPTH`

- **`none` (recomendado)**: Historia completa. Necesario para que Gitleaks detecte secretos en commits históricos.
- **`1`**: Solo el último commit. Más rápido, suficiente si solo usás SBOM/CodeQL.

## Uso

```bash
# Ejecutar el miner (lee config de .env)
python -m miner

# Ver opciones
python -m miner --help

# Listar repos sin clonar (dry-run)
python -m miner --dry-run

# Override de org y workers por CLI
python -m miner --org otra-org --workers 10

# Logging detallado
python -m miner -v

# Guardar resumen en JSON (útil para CI/CD)
python -m miner --output-json /tmp/miner-summary.json
```

## Con Docker

```bash
# Levantar solo la DB
docker compose up db

# Ejecutar el miner una vez
docker compose run --rm miner

# Ver logs
docker compose logs -f miner
```

## Estructura del proyecto

```
github-miner/
├── miner/
│   ├── __init__.py
│   ├── __main__.py     # Entrypoint CLI
│   ├── miner.py        # Lógica principal: GitHubClient + GitHubMiner
│   ├── db.py           # Capa de acceso a PostgreSQL
│   └── models.py       # Dataclasses: Organization, Repository
├── db/
│   └── schema.sql      # Schema completo del pipeline (todas las tablas)
├── config/
│   └── .env.example    # Plantilla de variables de entorno
├── tests/
│   └── test_miner.py   # Tests con mocks (sin llamadas reales a GitHub)
├── docker-compose.yml  # Infraestructura del pipeline completo
├── Dockerfile.miner
└── pyproject.toml
```

## Tests

```bash
pytest tests/ -v

# Con coverage
pytest tests/ -v --cov=miner --cov-report=term-missing
```

## Permisos de GitHub

El token necesita los siguientes scopes según el tipo de repos:

| Repos | Scope necesario |
|---|---|
| Solo públicos | `public_repo` |
| Privados | `repo` |
| Leer organización | `read:org` |

**Recomendación para producción**: usar una **GitHub App** en lugar de un PAT personal. Permite permisos más granulares y no expira.

## Próximos módulos

1. **Gitleaks Analyzer** — detecta secretos en el historial de commits
2. **SBOM Generator** — genera Software Bill of Materials con Syft
3. **Grype Scanner** — busca CVEs en las dependencias del SBOM
4. **CodeQL Analyzer** — análisis estático de código fuente
5. **Frontend Dashboard** — visualización de todos los hallazgos
