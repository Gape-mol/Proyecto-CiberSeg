# Especificación Proyecto P1 — Análisis de Vulnerabilidades en Software

> Documento de referencia para el proyecto semestral. Describe los requisitos formales
> y el estado de cumplimiento del repositorio actual.

---

## Descripción general

El proyecto consiste en construir una herramienta que detecte, analice y visualice vulnerabilidades en repositorios de una organización del **dataset AIDev**. La solución se compone de tres artefactos separados con responsabilidades bien definidas.

- **Organización analizada:** máximo 50 repositorios por organización.
- **Lenguajes obligatorios:** Python y JavaScript.
- **Entrega:** entorno completamente reproducible mediante Dev Containers.

---

## Artefacto 1 — Miner

**Propósito:** extraer vulnerabilidades de los repositorios de la organización.

**Pipeline obligatorio por repositorio:**

| Paso | Herramienta | Qué produce |
|------|-------------|-------------|
| 1 | `git clone` | Copia local del repositorio |
| 2 | **CodeQL** | Análisis estático de código (SARIF) |
| 3 | **Syft** | SBOM en formato CycloneDX |
| 4 | **Grype** | CVEs en dependencias (basado en el SBOM) |

**Requisitos del dataset de salida:**

Cada hallazgo debe incluir como mínimo:
- Tipo de vulnerabilidad
- Ubicación (archivo, línea cuando esté disponible)
- Severidad (cuando esté disponible)
- Repositorio de origen

El formato es libre pero debe ser **consistente y reutilizable**.

**Procesamiento:** debe poder procesar múltiples repositorios de forma **continua**.

### Estado de implementación

| Requisito | Estado | Implementación |
|-----------|--------|----------------|
| Clonar repos | ✅ | `pipeline.py:_process_repo()` + `stage_clone()` |
| Análisis CodeQL | ✅ | `pipeline.py:_run_codeql()` + `stage_codeql()` |
| SBOM con Syft | ✅ | `pipeline.py:_run_sbom()` + `stage_sbom()` |
| Grype sobre SBOM | ✅ | `pipeline.py:_run_grype()` + `stage_grype()` |
| Procesamiento continuo | ✅ | Flag `--continuous` con `--interval` configurable |
| Máximo 50 repos | ✅ | `REPO_LIMIT=50` por defecto en `MinerConfig` |
| Tipo en dataset | ✅ | `rule_id`/`rule_name` (CodeQL), `vulnerability_id` (Grype), `rule_id` (Gitleaks) |
| Ubicación en dataset | ✅ | `location`, `file_path`, `start_line` en todos los findings |
| Severidad en dataset | ✅ | Campo `severity` en todos los findings |
| Repo de origen | ✅ | Campo `repo_id` en todas las colecciones de hallazgos |
| **Extra: Gitleaks** | ➕ | `pipeline.py:_run_gitleaks()` + `stage_gitleaks()` |

---

## Artefacto 2 — Analyzer

**Propósito:** análisis exploratorio y sistemático de los hallazgos generados por el Miner.

**Implementación:** notebooks (Jupyter u otro).

**Análisis mínimo requerido:**
- Caracterización por **tipo, frecuencia y severidad** de vulnerabilidades.
- **Distribución entre repositorios** de la organización.
- Identificación de **patrones relevantes** en los resultados.

### Estado de implementación

| Requisito | Estado | Implementación |
|-----------|--------|----------------|
| Input desde el Miner | ✅ | Todos los notebooks leen `/data/secpipeline.json` (configurable via `DB_PATH`) |
| Implementado como notebooks | ✅ | 5 notebooks en `analyzers/` |
| Tipo, frecuencia, severidad | ✅ | `00_overview.ipynb` + notebooks por herramienta |
| Distribución entre repositorios | ✅ | Rankings y comparativas en `00_overview.ipynb` |
| Identificación de patrones | ✅ | Análisis por CWE (CodeQL), CVSS (Grype), tipo de secreto (Gitleaks) |
| **Extra: análisis de secretos** | ➕ | `04_gitleaks.ipynb` — secretos por autor, línea temporal, repos más expuestos |

---

## Artefacto 3 — Visualizer

**Propósito:** presentar los resultados consolidados de forma clara y comprensible.

**Requisitos funcionales:**
- Mostrar la **distribución de vulnerabilidades**.
- Permitir **comparar repositorios**.
- Comunicar **diferencias en severidad y tipo**.
- Idealmente, **actualizarse** a medida que el Miner genera nuevos datos.

### Estado de implementación

| Requisito | Estado | Implementación |
|-----------|--------|----------------|
| Distribución de vulnerabilidades | ✅ | Charts por herramienta y severidad en `index.html` (Chart.js) |
| Comparar repositorios | ✅ | Tablas y gráficos por repo en el dashboard |
| Diferencias en severidad y tipo | ✅ | Código de colores: critical/high/medium/low |
| Actualización dinámica | ✅ | Auto-refresh cada 2 segundos vía polling en `index.html` |
| Implementado con JavaScript | ✅ | ES6 vanilla JS + Chart.js (sin herramientas de build) |

---

## Arquitectura general

**Requisito:** tres componentes separados con intercambio de datos claro y separación explícita entre extracción, análisis y visualización.

| Requisito | Estado | Implementación |
|-----------|--------|----------------|
| Tres componentes separados | ✅ | `miner/`, `analyzers/`, `data-visualizer/` como unidades independientes |
| Intercambio de datos claro | ✅ | `/data/secpipeline.json` como contrato único entre componentes |
| Separación extracción/análisis/visualización | ✅ | Cada componente consume la salida del anterior sin acoplamiento |

---

## Lenguajes

| Requisito | Estado | Implementación |
|-----------|--------|----------------|
| Python | ✅ | Miner (Python 3.12), notebooks (pandas/matplotlib), servidor del visualizer |
| JavaScript | ✅ | `index.html` con Chart.js y ES6 (dashboard interactivo) |

---

## Reproducibilidad

| Requisito | Estado | Implementación |
|-----------|--------|----------------|
| Dev Container | ✅ | `.devcontainer/devcontainer.json` + `Dockerfile` |
| CodeQL incluido | ✅ | v2.17.3 — instalado en `.devcontainer/Dockerfile` |
| Syft incluido | ✅ | v1.4.1 — instalado en `.devcontainer/Dockerfile` |
| Grype incluido | ✅ | v0.78.0 — instalado en `.devcontainer/Dockerfile` |
| Python incluido | ✅ | Python 3.12 como imagen base |
| Node.js incluido | ✅ | Node.js 20 LTS instalado en `.devcontainer/Dockerfile` |
| Sin configuraciones adicionales | ✅ | `post-create.sh` instala deps Python y crea `.env` automáticamente |

---

## Resumen de cumplimiento

El proyecto cumple con **todos** los requisitos formales de la especificación P1.

Los elementos que superan la especificación son:
- **Gitleaks** como cuarta herramienta (secretos en historial de commits).
- **Analisis en paralelo por repositorio** — mantiene dependencias y simplifica la orquestacion.
- **Modo continuo** con intervalo configurable.
- **Selección inteligente de repos** por actividad reciente y popularidad (no solo tomar los primeros 50).
