# DataGuard AI

DataGuard AI is an implemented local-first prototype for data-quality incident detection and guarded response. It includes deterministic synthetic data, structured quality checks, DQF/DIP processing, held-out detection evaluation, evidence-grounded RCA and runbook retrieval, typed simulated actions with server-side approval, post-action verification, SQLite persistence, FastAPI, and an API-only Streamlit dashboard. Actions are local simulations; there is no production data or scheduler connector.

## Submission links and readiness

- **Project Google Drive folder:** [Open the group submission folder](https://drive.google.com/drive/folders/14eESeGpSued7mg_-TGGuvwqHC8BtWPKE?usp=sharing)
- **GitHub source (submitted branch):** [DIP-PROJECT-23CD3049-23CD3001 / `dataguardv1`](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1)
- **Four-page IEEE paper PDF:** [Download the compiled paper](output/23cd3049_23cd3001_DataGuardAI.pdf) (4 pages; separately upload this PDF)
- **Combined project presentation:** [Download the 11-slide PPTX](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/output/DataGuard_AI_SIH_Integrated_v5.pptx)
- **IEEE paper source:** [Open the LaTeX source](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/output/DataGuard_AI_IEEE.tex)
- **Evaluation protocol and measured results:** [Read the evaluation report](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/docs/evaluation_protocol.md)
- **Architecture and requirements:** [Read the architecture specification](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/Legacy_Docs_Imp/ARCHITECTURE_AND_REQUIREMENTS.md)
- **Project iteration ledger:** [Read `ACTION.md`](ACTION.md)

### Source, data, results, and dashboard evidence

- Runtime source: [DataGuard package](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1/src/datagard), [dashboard](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/dashboard/app.py), and [tests](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1/tests).
- Reproducible input and labels: [synthetic run data](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/artifacts/data/pipeline_runs.jsonl) and [separate scenario truth](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/blob/dataguardv1/artifacts/data/scenario_truth.jsonl). These are synthetic, not externally collected production records.
- Detection outputs: [metrics](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1/artifacts/evaluation/detection), including predictions and confusion matrices.
- DIP outputs: [metrics](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1/artifacts/evaluation/dip) and [fingerprint masks and overlays](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1/artifacts/fingerprints).
- Operations outputs: [RCA, retrieval, and policy cases](https://github.com/AARNAKUMAR/DIP-PROJECT-23CD3049-23CD3001/tree/dataguardv1/artifacts/evaluation/operations).
- Genuine UI captures: [DQF processing](output/dashboard_screenshots/dqf_processing.png), [incident investigation](output/dashboard_screenshots/incident_investigation.png), and [actions and approvals](output/dashboard_screenshots/actions_approvals.png).

### Course checklist

| Requirement | Repository evidence | Status |
|---|---|---|
| Separate four-page IEEE conference paper PDF | `output/23cd3049_23cd3001_DataGuardAI.pdf`; verified as four pages | Ready; upload this PDF separately |
| Supporting files uploaded individually, no ZIP | The combined PPTX is 682,917 bytes; the PDF is 72,729 bytes; both are below 10 MB | Ready to select individually; choose no more than 10 supporting files |
| Problem statement and solution | Slides 2–3 of the combined deck | Present |
| Methodology, flowchart, and pseudocode | Paper Section III describes the method, includes Fig. 1 workflow diagram, and lists the five-step closed-loop procedure; the deck also shows the workflow | Present in the paper; deck could add a dedicated pseudocode slide if desired |
| State of the art and references | Paper Section II is titled “Related Work and State of the Art”; it cites eight entries in the references section | Present in the paper; no separate references slide in the optional deck |
| Implementation/source code | Source package, dashboard, tests, and setup instructions are linked above | Present in GitHub |
| Dataset/data source | Deterministic synthetic run records and separate truth labels are saved and linked above | Present; clearly label as synthetic |
| DIP novelty/USP | DQF encoding and segmentation methods are described and evaluated | Present; claims are limited to this synthetic benchmark |
| Results and dashboard | Held-out metrics, saved outputs, and genuine dashboard screenshots are included | Present; small synthetic and fixed-case evaluation limits are disclosed |
| Google Drive folder link | Group folder linked above | Present; check access/sharing in the submission form |

The supplied IEEE PDF is 72,729 bytes and was verified as four pages (Letter size, unencrypted); all four rendered pages were visually checked for clipping and obvious layout defects. It includes related work/state of the art, the workflow figure, a numbered algorithmic procedure, measured results, and eight references. The 11-slide PPTX is 682,917 bytes and passes package-integrity checks. Its section labels skip from 04 to 08 and repeat 10 on all three dashboard slides; correcting those labels would improve polish, but the required paper covers the state-of-the-art and references sections.

The supplied submission instructions say to name each uploaded file with the required `Name_RollNumber_` prefix, upload the IEEE PDF as its own file, and avoid ZIP files. The PDF currently has a roll-number-based filename but no student name prefix; apply the exact required name/roll-number prefix for each member's form. Submit the group form separately for each member as instructed and confirm Drive access for the reviewer.

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
