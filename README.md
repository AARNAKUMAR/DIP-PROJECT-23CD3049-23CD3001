# DataGuard AI

DataGuard AI is an implemented local-first prototype for data-quality incident detection and guarded response. It includes deterministic synthetic data, structured quality checks, DQF/DIP processing, held-out detection evaluation, evidence-grounded RCA and runbook retrieval, typed simulated actions with server-side approval, post-action verification, SQLite persistence, FastAPI, and an API-only Streamlit dashboard. Actions are local simulations; there is no production data or scheduler connector.

## Setup

Requires Python 3.11 or newer and `uv`.

```bash
uv sync --extra dev
uv run uvicorn datagard.main:app --app-dir src --reload
```

The health endpoint is available at `http://127.0.0.1:8000/health`.
The first API startup creates the configured local SQLite store at `artifacts/dataguard.sqlite3`, seeds the deterministic 360-run dataset if it is empty, and writes separate run/truth JSONL inputs under `artifacts/data/`.

## API workflow

FastAPI docs are available at `http://127.0.0.1:8000/docs`. The versioned API exposes pipeline and run inspection, analysis, incident investigation and planning, approval, action execution, timelines, evaluation/dashboard summaries, and allowlisted DQF image artifacts. The Streamlit UI calls these routes; action state changes remain owned by the shared application service and orchestrator.

To demonstrate an incident: choose a run from `GET /api/v1/runs`, call its `/analyze` route, then investigate one returned incident. Use action IDs from the returned typed proposals to execute quarantine/rerun or to request approval for an isolated schema-alignment simulation. Source run records remain unchanged.

## Run the dashboard

Start the API and dashboard in separate terminals:

```bash
uv run uvicorn datagard.main:app --app-dir src --reload
uv run streamlit run dashboard/app.py
```

The dashboard reads the API base URL from `dashboard_api_base_url` in `configs/default.yaml`. Its five views cover overview, DQF processing, incident investigation, actions/approvals, and evaluation. DQF images are served through an artifact-ID/stage allowlist. Screens do not read file paths or query SQLite directly. Genuine screenshots from the running app are in `output/dashboard_screenshots/` and in the presentation.

## Generate CP-1 synthetic input

```bash
uv run python -m datagard.ingestion
```

This writes `artifacts/data/pipeline_runs.jsonl` and `artifacts/data/scenario_truth.jsonl`. With the default configuration there are 360 runs across ten scenarios. The truth file is separate from model inputs. The configured seed, episode count, and persistence length are in `configs/default.yaml`; output artifacts are local and git-ignored.

## Run the CP-3 DIP benchmark

```bash
uv run python -m datagard.visual_inspection
```

This command refreshes the synthetic inputs, fits channel baselines on the training partition's clean runs, and evaluates held-out incident groups. It saves fingerprints, validity and ground-truth masks, global/adaptive masks, overlays, region maps and manifests under `artifacts/fingerprints/`; aggregate and per-scenario measurements are written to `artifacts/evaluation/dip/`. Measured results are in `docs/evaluation_protocol.md`. The adaptive/morphological alternative currently performs worse than the global Otsu baseline on the held-out synthetic set, so no improvement claim is made.

To run smoke, foundation, quality and DIP tests:

```bash
uv run pytest -q
```

## Run the CP-4 detector benchmark

```bash
uv run python -m datagard.evaluation
```

This uses incident-grouped train/validation/test partitions, fits preprocessing and Isolation Forest on clean training rows, selects score thresholds using validation F1, and evaluates the test partition once. It saves model artifacts under `artifacts/models/` and JSON/CSV metrics, predictions, confusion matrices, scenario metrics and split IDs under `artifacts/evaluation/detection/`. See [docs/evaluation_protocol.md](docs/evaluation_protocol.md) for denominators and measured tradeoffs.

## Current workflow status

Run the fixed query, RCA, and policy evaluation with `uv run python -m datagard.operational_evaluation`; query-level scores and timings are saved under `artifacts/evaluation/operations/`.

| Capability | Status |
|---|---|
| Package, settings, logging, health API | Implemented (CP-0) |
| Deterministic scenarios, canonical run records, strict JSONL ingestion, schema diff and lineage | Implemented (CP-1) |
| Structured quality rules and canonical feature vector | Implemented (CP-2) |
| DQF encoding, validity mask, DIP-B0/DIP-P1, mapped regions and saved artifacts | Implemented (CP-3) |
| Isolation Forest, rule baseline, validation thresholding, DIP ablation | Implemented and measured (CP-4) |
| Incident deduplication, evidence-based RCA, local TF-IDF runbook retrieval | Implemented (CP-5) |
| Single orchestrator, typed tool registry, quarantine/rerun, approved schema repair and verification | Implemented (CP-6) |
| SQLite persistence and FastAPI run/incident/action/evaluation API | Implemented (CP-7) |
| Persistence/API | SQLite and application routes; restart checked (CP-7) |
| Dashboard | Implemented; five API-backed views (CP-8) |
| Retrieval/RCA/policy metrics | Query-level and three safety probes saved (CP-9) |
| Paper and presentation | Updated IEEE LaTeX source and 11-slide combined SIH deck with genuine dashboard screenshots |

The manuscript source is `output/DataGuard_AI_IEEE.tex`. The combined presentation is `output/DataGuard_AI_SIH_Integrated_v5.pptx`; exact denominators and limitations are in [docs/evaluation_protocol.md](docs/evaluation_protocol.md).

See [ACTION.md](Legacy_Docs_Imp/ACTION.md) for verified checkpoint status and [ARCHITECTURE_AND_REQUIREMENTS.md](Legacy_Docs_Imp/ARCHITECTURE_AND_REQUIREMENTS.md) for the complete target.
