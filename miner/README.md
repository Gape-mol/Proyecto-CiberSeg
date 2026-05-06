# Miner - estado actual (Proyecto-CiberSeg)

Este README describe el comportamiento actual del componente Miner y su relacion con el resto del proyecto. No propone cambios; solo documenta lo que ya existe en el codigo.

## Proposito y alcance

El Miner extrae repositorios de una organizacion de GitHub (dataset AIDev), ejecuta analisis de seguridad por repo y genera un dataset JSON estructurado. El flujo obligatorio de P1 (clone -> CodeQL -> Syft -> Grype) esta implementado y se ejecuta de forma continua si se habilita el modo continuo.

## Cumplimiento P1 (solo Miner)

| Requisito | Estado | Implementacion actual |
|---|---|---|
| Clonar repos | OK | `pipeline.py:_process_repo()` + `stage_clone()` |
| Analisis CodeQL | OK | `pipeline.py:_run_codeql()` + `stage_codeql()` |
| SBOM con Syft | OK | `pipeline.py:_run_sbom()` + `stage_sbom()` |
| Grype sobre SBOM | OK | `pipeline.py:_run_grype()` + `stage_grype()` |
| Dataset con tipo/ubicacion/severidad/repo | OK | `store/json_store.py` y submodulos normalizan campos |
| Procesamiento continuo | OK | `__main__.py` con `--continuous` y `--interval` |
| Extra (no requerido) | OK | Gitleaks en `pipeline.py:_run_gitleaks()` + `stage_gitleaks()` |

## Flujo general (call graph resumido)

```
python -m miner
  -> miner/__main__.py:run() -> main()
     -> MinerConfig.from_env()                       (config.py)
     -> JsonStore.connect()                          (store/json_store.py)
     -> GitHubMiner.run()                            (miner_service.py)
        -> GitHubClient.get_org()                    (git/client.py)
        -> JsonStore.upsert_organization()           (store/json_store.py)
        -> GitHubMiner._collect_repos()              (miner_service.py)
           -> GitHubClient.list_org_repos()          (git/client.py)
           -> Repository.from_api()                  (models.py)
           -> JsonStore.upsert_repository()          (store/json_store.py)
     -> Pipeline.run(repos)                          (pipeline.py)
        -> _process_repo()                           (pipeline.py)
           -> stage_clone()                          (stages/clone.py)
              -> clone_or_update_repo()              (git/ops.py)
           -> JsonStore.mark_repo_cloned()           (store/json_store.py)
           -> _run_gitleaks()                        (pipeline.py)
           -> _run_sbom()                            (pipeline.py)
           -> _run_codeql()                          (pipeline.py)
           -> _run_grype()                           (pipeline.py)
```

## Pipeline actual (detalles por etapa)

El pipeline procesa un repositorio a la vez. Tras el clone, ejecuta Gitleaks, SBOM y CodeQL en paralelo, y luego ejecuta Grype cuando el SBOM esta listo.

1) Clone
   - Funcion: `stages/clone.py:stage_clone()`.
   - Llama a `git/ops.py:clone_or_update_repo()` que decide entre `git clone` o `git fetch`.
   - Si el clone es exitoso, guarda `clone_path` y `commit_sha` en `store/json_store.py:mark_repo_cloned()`.

2) Gitleaks (extra)
   - Funcion: `pipeline.py:_run_gitleaks()` + `stages/gitleaks.py:stage_gitleaks()`.
   - Ejecuta `gitleaks detect` y produce JSON por repo.
   - Persiste en:
     - `store/json_store.py:save_gitleaks_scan()`
     - `store/json_store.py:save_gitleaks_findings()`

3) SBOM (Syft)
   - Funcion: `pipeline.py:_run_sbom()` + `stages/sbom.py:stage_sbom()`.
   - Ejecuta `syft <repo> --output cyclonedx-json=...`.
   - Persiste en:
     - `store/json_store.py:save_sbom_scan()`
     - `store/json_store.py:save_sbom_components()`

4) Grype
   - Funcion: `pipeline.py:_run_grype()` + `stages/grype.py:stage_grype()`.
   - Ejecuta `grype sbom:<sbom_path> --output json`.
   - Persiste en:
     - `store/json_store.py:save_grype_scan()`
     - `store/json_store.py:save_grype_findings()` (incluye severidad y CVSS cuando existe)

5) CodeQL
   - Funcion: `pipeline.py:_run_codeql()` + `stages/codeql.py:stage_codeql()`.
   - Mapea el lenguaje principal del repo con `CODEQL_LANGUAGE_MAP`.
   - Si el lenguaje no esta soportado, marca la etapa como exitosa pero con `skipped`.
   - Ejecuta:
     - `codeql database create` (con `--build-mode none` para JS/Python/Ruby)
     - `codeql database analyze` con el pack `*-security-and-quality`.
   - Persiste en:
     - `store/json_store.py:save_codeql_scan()`
     - `store/json_store.py:save_codeql_findings()` (normaliza severidad y CWE)

## Dataset de salida (secpipeline.json)

El dataset se escribe en la ruta `DB_PATH` (default `/data/secpipeline.json`) con el formato `miner-json-v1`. Cada escritura en `store/json_store.py` hace flush completo para mantener el archivo actualizado.

Colecciones principales:

- `organizations`, `repositories`
- `gitleaks_scans`, `gitleaks_findings`
- `sbom_scans`, `sbom_components`
- `grype_scans`, `grype_findings`
- `codeql_scans`, `codeql_findings`

Campos minimos de hallazgos (P1):

- Tipo: `rule_id` (CodeQL/Gitleaks) o `vulnerability_id` (Grype)
- Ubicacion: `file_path` + `location` (cuando aplica)
- Severidad: `severity` (normalizada a high/medium/low cuando es posible)
- Repo: `repo_id`

## Mapa de archivos (Miner) y relaciones

| Archivo | Contenido principal | Relaciones / llamadas |
|---|---|---|
| `miner/__main__.py` | CLI, logging, modo continuo, reset | Importa `MinerConfig`, `GitHubMiner`, `Pipeline`, `JsonStore` |
| `miner/config.py` | `MinerConfig` — carga variables de entorno | Usado por `__main__.py` |
| `miner/miner.py` | Re-exports para compatibilidad | Expone `GitHubClient`, `clone_or_update_repo`, `GitHubMiner` |
| `miner/miner_service.py` | `GitHubMiner` — seleccion de repos y persistencia | Usa `git/` y `store/` |
| `miner/pipeline.py` | `Pipeline` + `PipelineConfig` — orquestador por repo | Llama a etapas en `stages/` y persiste con `store/` |
| `miner/models.py` | Dataclasses `Organization` y `Repository` | Usado en todo el miner |
| `miner/__init__.py` | Exporta clases publicas del paquete | Facilita imports del paquete |
| `miner/git/client.py` | `GitHubClient` — API REST paginada con reintentos | Usado por `miner_service.py` |
| `miner/git/ops.py` | `clone_or_update_repo()` — decide entre `git clone` / `git fetch` | Usado por `stages/clone.py` |
| `miner/stages/clone.py` | `stage_clone()` | Llama a `git/ops.py` |
| `miner/stages/gitleaks.py` | `stage_gitleaks()` | Produce JSON de hallazgos |
| `miner/stages/sbom.py` | `stage_sbom()` | Produce CycloneDX JSON via Syft |
| `miner/stages/grype.py` | `stage_grype()` | Consume SBOM; produce CVEs via Grype |
| `miner/stages/codeql.py` | `stage_codeql()` | `codeql database create` + `analyze` |
| `miner/stages/types.py` | `StageResult`, `repo_id()` | Tipo compartido entre todas las etapas y `pipeline.py` |
| `miner/store/json_store.py` | `JsonStore` — fachada publica del store | Delega en los submodulos de `store/` |
| `miner/store/core.py` | `StoreCore` — I/O al JSON, lock asyncio, flush | Usado por `JsonStore` |
| `miner/store/repo_store.py` | Upsert y estado de `organizations`/`repositories` | Usado por `JsonStore` |
| `miner/store/scan_store.py` | Scans de Gitleaks y sus findings | Usado por `JsonStore` |
| `miner/store/sbom_store.py` | Scans de Syft y componentes SBOM | Usado por `JsonStore` |
| `miner/store/grype_store.py` | Scans de Grype y CVEs | Usado por `JsonStore` |
| `miner/store/codeql_store.py` | Scans de CodeQL y hallazgos estaticos | Usado por `JsonStore` |
| `miner/store/types.py` | `StoreCollections` — nombres de colecciones | Usado por `StoreCore` y stores |
| `miner/store/utils.py` | `now_str()` y helpers de timestamp | Usado por stores |
| `miner/pyproject.toml` | Dependencias y tooling (ruff, mypy, pytest) | Define entorno del Miner |

Relaciones clave entre archivos:

- `pipeline.py` depende de `stages/` para analisis y de `store/` para persistir.
- `miner_service.py` depende de `git/` para API y de `store/` para upsert.
- `store/json_store.py` es la fachada publica; `core.py` gestiona el I/O; cada `*_store.py` maneja una herramienta.
- `store/` depende de `models.py` para reconstruir entidades.
- `__main__.py` une todo: configura, valida token/org, corre `GitHubMiner` y luego `Pipeline`.

## Integracion con Analyzer y Visualizer

- El Miner produce `secpipeline.json` y reportes en `/data/reports/<repo>/`.
- Los notebooks en `analyzers/` y el dashboard en `data-visualizer/` consumen el JSON sin acoplarse al runtime del Miner.

## Notas de comportamiento actuales

- Seleccion de repos: trae hasta `REPO_LIMIT * 4` repos ordenados por actividad reciente; filtra por `REPO_RECENT_DAYS` y completa con los mas populares si falta.
- Clone depth: `CLONE_DEPTH=none` (default) mantiene historial completo para Gitleaks.
- Cada escritura en `store/json_store.py` reescribe el JSON completo para consistencia con el visualizer.
