# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Proyecto-CiberSeg** is a security analysis pipeline that extracts repositories from a GitHub organization (AIDev dataset), runs four security tools in sequential pipeline stages (Gitleaks, Syft, Grype, CodeQL), and produces a structured JSON dataset. It includes Jupyter notebooks for analysis and an interactive JS dashboard.

## Running the System

### Recommended: Dev Container

Open in VS Code and reopen in container. All tools (CodeQL 2.17.3, Syft 1.4.1, Grype 0.78.0, Gitleaks 8.18.4, Python 3.12) are pre-installed. `post-create.sh` installs Python deps and copies `.env.example` to `.env` automatically.

```bash
# Configure credentials (only GITHUB_TOKEN and GITHUB_ORG are required)
nano /workspace/.env

# Run the miner
python -m miner
python -m miner --dry-run          # Preview repos without cloning
python -m miner --limit 10 -v      # Process 10 repos with verbose logging
python -m miner --reset            # Delete all data and start fresh
python -m miner --continuous --interval 300  # Repeat every 5 min

# Launch the visualizer (port 4173) — serve.py proxies /data/ requests to /data/secpipeline.json
python /workspace/data-visualizer/serve.py

# Launch Jupyter for analysis notebooks
jupyter lab --ip=0.0.0.0 --no-browser --allow-root
```

### Docker Compose

```bash
docker compose run --rm miner
docker compose run --rm miner python -m miner --dry-run
docker compose up visualizer   # plain HTTP server; dataset_data volume mounted at /app/data/
```

## Tests

```bash
cd miner
pip install -e ".[dev]"       # First time only
pytest tests/ -v
pytest tests/ -v --cov=miner  # With coverage
pytest tests/test_pipeline.py -v  # Single test file
```

Tests use `respx` to mock GitHub API calls and `pytest-mock` to mock subprocesses for pipeline stages. `asyncio_mode = "auto"` is set in `pyproject.toml` so no `@pytest.mark.asyncio` decorator is needed.

## Linting and Type Checking

```bash
cd miner
ruff check miner/          # Lint
ruff format miner/         # Auto-format
mypy miner/                # Type check (strict mode)
```

## Architecture

The pipeline runs in **three sequential phases**, each using `asyncio.Queue` to fan work across parallel workers:

```
Phase 1 — Clone (clone_workers)
    ↓ feeds two queues simultaneously
Phase 2 — Gitleaks (gitleaks_workers) + SBOM/Syft (sbom_workers) [parallel]
    ↓ SBOM success feeds two more queues
Phase 3 — Grype (grype_workers) + CodeQL (codeql_workers) [parallel]
    ↓
/data/secpipeline.json   ←  written to disk after every DB operation
    ↓
analyzers/*.ipynb          data-visualizer/ (polls secpipeline.json every 2s)
```

Each phase completes fully before the next begins — `Pipeline.run()` in `pipeline.py` does `asyncio.gather()` per phase, not a single streaming gather.

### Key Files

| File | Role |
|---|---|
| `miner/miner/__main__.py` | CLI entrypoint, arg parsing, `ColorFormatter` logging, orchestration loop |
| `miner/miner/miner.py` | `GitHubClient` (API + retry via tenacity), `GitHubMiner` (repo selection), `clone_or_update_repo` |
| `miner/miner/pipeline.py` | `Pipeline` class with 5 async stage workers; `StageResult` dataclass |
| `miner/miner/db.py` | `Database` class — in-memory JSON store with `asyncio.Lock`; flushes to disk on every write |
| `miner/miner/models.py` | `Organization` and `Repository` dataclasses with `from_api()` constructors |
| `data-visualizer/index.html` | Dashboard (Chart.js, vanilla ES6, no build tools) |
| `data-visualizer/serve.py` | HTTP server: serves `index.html` from its own directory, proxies `/data/*` to `DATA_ROOT` |

### Non-obvious patterns

**Queue shutdown sentinel** — `_DONE = None` in `pipeline.py`. After each phase, the orchestrator injects one `None` per worker into the queue; workers break their loop on `None`. This prevents a fast worker from closing downstream queues before slower peers finish.

**DB flush-on-write** — `Database._flush_unlocked()` rewrites the entire JSON file after every `save_*` call. There is no explicit commit step. This means `secpipeline.json` is always up-to-date and the visualizer sees live data with no extra work.

**serve.py proxy** — In the Dev Container the data lives at `/data/` but the visualizer HTML is in `data-visualizer/`. `serve.py` intercepts any request to `/data/*` and reads from `DATA_ROOT` (defaults to `/data`), then falls back to `SimpleHTTPRequestHandler` for everything else. In Docker Compose the volume is mounted inside the serve directory so no proxy is needed.

**Repo selection** (`miner.py:GitHubMiner._collect_repos`) — Fetches `REPO_LIMIT × 4` repos sorted by push date. Filters by `REPO_RECENT_DAYS`. If enough recent repos exist, sorts by stars and takes the top `REPO_LIMIT`; otherwise pads with most-starred inactive repos.

### Output Dataset (`/data/secpipeline.json`)

Collections defined in `db._COLLECTIONS`:

| Collection | Content |
|---|---|
| `organizations` | Org metadata |
| `repositories` | Repo state (`miner_status`), clone path, last commit SHA |
| `gitleaks_scans` | Per-repo scan record (timestamp, findings_count) |
| `gitleaks_findings` | Secret findings: rule_id, file_path, line, author, commit |
| `sbom_scans` | Per-repo SBOM generation record |
| `sbom_components` | Components: name, version, purl, ecosystem, license |
| `grype_scans` | Per-repo Grype scan record |
| `grype_findings` | CVEs: vulnerability_id, severity, cvss_score, package, fix_versions |
| `codeql_scans` | Per-repo CodeQL scan record (language, findings_count) |
| `codeql_findings` | Static findings: rule_id, cwe[], severity, file_path, start_line |
| `pipeline_runs` | Reserved; currently never written |

Risk score formula (notebooks + dashboard): `Critical×10 + High×5 + Medium×2 + Low×1 + Secret×3`.

`Repository.miner_status` tracks per-repo pipeline state: `pending` → `cloning` → `cloned` → `error`.

## Environment Variables

**Required:**
- `GITHUB_TOKEN` (or `GH_TOKEN`) — GitHub PAT with `read:org` + `repo` scopes
- `GITHUB_ORG` — Organization slug

**Key optional (defaults):**
- `DB_PATH` — `/data/secpipeline.json`
- `CLONE_ROOT` — `/data/repos`
- `REPORTS_ROOT` — `/data/reports`
- `REPO_LIMIT` — `50`
- `REPO_RECENT_DAYS` — `30`
- `CLONE_WORKERS` — `5`
- `GITLEAKS_WORKERS`, `SBOM_WORKERS`, `GRYPE_WORKERS` — `2` each
- `CODEQL_WORKERS` — `1` (CPU-intensive; keep low)
- `CLONE_DEPTH` — `none` (set to `1` for shallow clones; reduces Gitleaks effectiveness)
- `RUN_CONTINUOUS` / `RUN_INTERVAL_SECONDS` — for continuous mode

## Analysis Notebooks

Notebooks in `analyzers/` read from `DB_PATH` (env var) or `/data/secpipeline.json`:
- `00_overview.ipynb` — Risk scoring and repo ranking across all tools
- `01_codeql.ipynb` — Static analysis findings (rules, CWEs, top affected files)
- `02_grype.ipynb` — Dependency CVE analysis (CVSS scores, remediation)
- `03_sbom.ipynb` — Software Bill of Materials (components, licenses, ecosystems)
- `04_gitleaks.ipynb` — Secret exposure (types, author timeline, top repos)

Install notebook dependencies: `pip install -r analyzers/requirements.txt`
