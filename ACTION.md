# ACTION.md - DataGuard AI project state and iteration ledger

> Mandatory IDE memory file. Update after every meaningful coding/configuration/documentation iteration. Keep the ledger append-only. Do not claim tests passed unless they were executed.

## Current state

- **Project:** HSR-AGAI-001 - Agentic Data Quality Incident Detection, Root-Cause and Remediation Agent
- **DIP contribution:** Data Quality Fingerprint image encoding + classical DIP segmentation and region evidence
- **Architecture:** Python modular monolith; FastAPI backend; Streamlit API client; SQLite persistence
- **Current checkpoint:** CP-9 - evaluation and release evidence (complete)
- **Current status:** CP-0 through CP-9 implemented: local data/quality/DIP/detection, incident/RCA/RAG, guarded orchestrator/tools, SQLite-backed API, API-only dashboard, saved measurements, paper source, and 11-slide combined SIH/DIP v6 presentation.
- **Latest verified tests:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q` - 28 passed, one upstream Starlette TestClient deprecation warning. Restart tests cover incident/timeline persistence and resuming approved repair. Presentation package/layout/import checks passed for the 11-slide combined deck.
- **Known decisions:** See `ARCHITECTURE_AND_REQUIREMENTS.md` and `docs/decisions.md`.
- **Current blockers:** No local prototype blocker. The supplied compiled IEEE PDF is included and verified as four pages. Synthetic data and small operational sets are not production evidence. Apply the form-specific `Name_RollNumber_` filename prefix to each upload. Cambria is assigned throughout editable deck text/theme; the local renderer lacks the font, so verify final wrapping in PowerPoint where Cambria is available.
- **Next smallest task:** Check the v6 presentation in PowerPoint with Cambria available; rename submission files for each student's form.

## Iteration ledger (append only)

### ITERATION 000 - 2026-11-10 - Architecture baseline prepared

- **Checkpoint:** CP-0 / pre-implementation
- **Requirement IDs:** G-01 through G-17; NFR-01 through NFR-12 (requirements defined, not implemented)
- **Change summary:** Established the source-grounded requirements, modular-monolith architecture, DIP fingerprint integration, technology stack, data/API contracts, action policy, evaluation protocol, checkpoints and IDE anti-overengineering rules.
- **Files created/modified:** `ARCHITECTURE_AND_REQUIREMENTS.md`, `ACTION.md`, `AGENTS.md` (governance documents)
- **Tests/commands run:** None; no application code exists yet.
- **Result:** Documentation baseline created; implementation status remains NOT STARTED.
- **Risks/unresolved:** DQF approach must be validated with the course instructor. The visual encoding must be evaluated against synthetic ground-truth masks; no DIP performance claims exist yet.
- **Next smallest task:** Execute CP-0 only. Do not begin CP-1 until CP-0 passes.

### ITERATION 001 - 2026-11-12 - CP-0 architecture freeze

- **Checkpoint:** CP-0 / minimal application foundation
- **Requirement IDs:** CP-0, G-13 (health/API foundation only), G-15 (setup foundation only), NFR-01, NFR-02, NFR-07, NFR-08, NFR-09, NFR-12
- **Change summary and reason:** Repository inspection found only architecture/governance materials and the IEEE manuscript; there was no application code, test suite, package metadata, or measured output. Added the minimum package, validated config, central logging, and health endpoint needed to establish the approved runtime boundary.
- **Files created/modified/deleted:** Added `.gitignore`, `pyproject.toml`, `uv.lock`, `configs/default.yaml`, `src/datagard/{__init__.py,config.py,logging_config.py,main.py}`, `tests/test_smoke.py`, `docs/decisions.md`; updated `ACTION.md`.
- **Existing logic reused:** No application logic existed to reuse. Requirements and module ownership were taken from `ARCHITECTURE_AND_REQUIREMENTS.md`.
- **New logic added (why it is not duplicative):** One settings loader, one logging setup, and one liveness route; no domain/business modules were scaffolded.
- **Tests/commands run:** `uv sync --extra dev`; `uv run pytest -q`; `uv run python -c 'from fastapi.testclient import TestClient; from datagard.main import app; response = TestClient(app).get("/health"); print(response.status_code, response.json())'`.
- **Results:** PASS - 2 tests passed; endpoint returned `200 {'status': 'ok', 'environment': 'development'}`. TestClient emitted a Starlette deprecation warning for using HTTPX; no failures.
- **Config/data/schema/docs changed:** Configuration, package metadata/lock, decision record and project state updated; no application data or schema introduced.
- **Known risks/regressions/blockers:** The paper describes a broad proposed architecture, while repository evidence now supports only CP-0. Detection/DIP/agent results and dashboard screenshots remain unavailable and must not be claimed until later checkpoints create real outputs. DQF course acceptance remains to be confirmed.
- **Next smallest task:** CP-1 deterministic data foundation; stop here until CP-0 review is accepted.

### ITERATION 002 - 2026-11-12 - CP-1 deterministic data foundation

- **Checkpoint:** CP-1 / data foundation
- **Requirement IDs:** G-01, G-02, G-15, NFR-03, NFR-04, NFR-08, NFR-09, NFR-12
- **Change summary and reason:** Added deterministic normal, defect, benign-seasonality, and missing-telemetry scenarios; kept evaluation truth out of run feature records; added strict JSONL ingestion, schema registry/diff, and lineage graph.
- **Files created/modified/deleted:** Added `src/datagard/contracts.py`, `src/datagard/ingestion.py`, `src/datagard/metadata.py`, `tests/test_data_foundation.py`, `README.md`; updated `configs/default.yaml`, `src/datagard/config.py`, `.gitignore`, `docs/decisions.md`, and `ACTION.md`.
- **Existing logic reused:** CP-0 `Settings`, Pydantic dependency, package structure, and test setup.
- **New logic added (why it is not duplicative):** One canonical `PipelineRun` contract and one metadata owner for schema comparison/lineage; synthetic truth is separate from quality/model input.
- **Tests/commands run:** `uv run pytest -q`; `uv run python -m datagard.ingestion`; `wc -l artifacts/data/pipeline_runs.jsonl artifacts/data/scenario_truth.jsonl`; `git diff --check`.
- **Results:** PASS - 6 tests passed; the configured generation produced 120 runs and 120 separate truth records; malformed input reports source line; schema and lineage tests pass. Existing Starlette TestClient deprecation warning remains.
- **Config/data/schema/docs changed:** Added seed, scenario count, and generated-data directory configuration; generated ignored JSONL artifacts; README and ADR updated.
- **Known risks/regressions/blockers:** Generator scenarios are synthetic and are not yet an evaluation result. The simple `distinct_count` proxy is not itself a duplicate count; CP-2 will clarify and add the canonical duplicate-rate evidence needed by quality checks.
- **Next smallest task:** CP-2 quality engine and canonical feature construction; no DIP or detector implementation before CP-2 acceptance.

### ITERATION 003 - 2026-11-12 - CP-2 quality rules and canonical features

- **Checkpoint:** CP-2 / quality engine
- **Requirement IDs:** G-03, NFR-02, NFR-03, NFR-08, NFR-12
- **Change summary and reason:** Added one deterministic structured quality engine for nulls, duplicates, row-count loss, schema differences, configured ranges, history-based distribution shifts, run failure, and missing telemetry. Added a sole canonical feature-vector builder with YAML-owned ordering.
- **Files created/modified/deleted:** Added `src/datagard/quality.py`, `src/datagard/features.py`, `tests/test_quality_features.py`; updated `src/datagard/config.py`, `src/datagard/contracts.py`, `configs/default.yaml`, `src/datagard/ingestion.py`, `README.md`, `docs/decisions.md`, and `ACTION.md`.
- **Existing logic reused:** CP-1 canonical run/field/schema contracts, `SchemaRegistry.diff`, deterministic scenarios, CP-0 settings and test suite.
- **New logic added (why it is not duplicative):** `quality.py` is the only rule evaluator; `features.py` only maps canonical telemetry/findings into the single configured numeric vector and does not decide rule outcomes.
- **Tests/commands run:** `uv run pytest -q`.
- **Results:** PASS - 9 tests passed; clean data yields no findings; each tested defect family yields its expected rule IDs; finding IDs are stable; vector names/order and row/drop features are verified. Initial fixture failure for missing telemetry was corrected before final pass. Starlette TestClient deprecation warning remains.
- **Config/data/schema/docs changed:** Added central quality thresholds/ranges and feature ordering; documented the current CP-2 implementation and history-baseline behavior.
- **Known risks/regressions/blockers:** Distribution baselines are supplied by callers for now; fit/freeze discipline and model use belong to CP-4. No DIP artifacts or performance measurements exist yet.
- **Next smallest task:** CP-3 DQF encoding/processing and segmentation metrics.

### ITERATION 004 - 2026-11-12 - CP-3 ownership conflict recorded

- **Checkpoint:** CP-3 / DIP pipeline (not started)
- **Requirement IDs:** G-16, NFR-12
- **Change summary and reason:** Recorded conflicting DIP ownership instructions before implementation. The root operating contract assigns encoding to `dip/encoder.py` and image operations to `dip/processor.py`; the architecture report §6.3/§6.4 assigns both to `visual_inspection.py`.
- **Files created/modified/deleted:** Updated `ACTION.md` and `docs/decisions.md` only.
- **Existing logic reused:** No DIP code exists.
- **New logic added (why it is not duplicative):** No code added. A proposal to keep `dip/encoder.py` and `dip/processor.py` as sole owners and use `visual_inspection.py` only as a thin facade requires confirmation before application.
- **Tests/commands run:** None; documentation-only conflict record.
- **Results:** NOT RUN (no code changed).
- **Config/data/schema/docs changed:** Decision record and current blocker summary updated.
- **Known risks/regressions/blockers:** CP-3 and downstream DIP-dependent checkpoints remain gated until module ownership is resolved. DQF course acceptance is also not yet confirmed.
- **Next smallest task:** Confirm the canonical DIP ownership layout; then implement CP-3 and update the architecture record consistently.

### ITERATION 005 - 2026-11-12 - CP-3 DQF and segmentation benchmark

- **Checkpoint:** CP-3 / DIP pipeline
- **Requirement IDs:** G-16, G-17 (DIP evidence), NFR-02, NFR-03, NFR-08, NFR-09, NFR-11, NFR-12
- **Change summary and reason:** Resolved module ownership in the architecture record: `dip/encoder.py` owns DQF encoding; `dip/processor.py` owns image operations; `visual_inspection.py` only composes them. Added calibrated channel baselines, explicit validity masks, Otsu baseline, adaptive-threshold/morphology alternative, connected regions and mapping, grouped held-out synthetic-mask evaluation, and saved image/CSV/JSON outputs. Increased each scenario to persistent three-run episodes and randomized the episode schedule with the fixed seed to create useful windows and group holdouts.
- **Files created/modified/deleted:** Added `src/datagard/dip/{__init__.py,encoder.py,processor.py,evaluation.py}`, `src/datagard/visual_inspection.py`, `tests/test_dip.py`, `docs/evaluation_protocol.md`; updated `ARCHITECTURE_AND_REQUIREMENTS.md`, `pyproject.toml`, `uv.lock`, `configs/default.yaml`, `src/datagard/{config.py,contracts.py,ingestion.py}`, `README.md`, `docs/decisions.md`, and `ACTION.md`.
- **Existing logic reused:** CP-1 `PipelineRun`, `ScenarioTruth`, schema registry and separate truth file; CP-2 centralized quality findings remain untouched. Baseline schema comparisons reuse `SchemaRegistry.diff`.
- **New logic added (why it is not duplicative):** One encoder and one processor under the operating-contract owners; the evaluation module alone computes segmentation metrics. DIP creates visual evidence and never duplicates quality-rule decisions.
- **Tests/commands run:** `uv sync --extra dev`; `uv run pytest -q`; `uv run python -m datagard.visual_inspection`; `python3 -m compileall -q src tests`; `git diff --check`; inspected the saved fingerprint, ground-truth mask, and overlays.
- **Results:** PASS - 12 tests passed. Held-out split: 252 training runs (27 clean baseline-fit runs) and 108 held-out runs; 90 covered by 3 complete windows (83.33%). On 1,024 valid pixels (90 positive): DIP-B0 TP=90, FP=51, FN=0, TN=883, precision=0.6383, recall=1.0000, F1=0.7792, IoU=0.6383; DIP-P1 TP=90, FP=375, FN=0, TN=559, precision=0.1935, recall=1.0000, F1=0.3243, IoU=0.1935. Median processing times on the current environment: 0.2413 ms (B0) and 0.1560 ms (P1) per fingerprint. P1 did not improve over B0. Starlette TestClient deprecation warning remains.
- **Config/data/schema/docs changed:** Added all DQF channel/threshold/filter/morphology/window/split parameters to central YAML; dependencies are NumPy and headless OpenCV (documented with alternatives/trade-off). Saved local artifacts under `artifacts/fingerprints/` and `artifacts/evaluation/dip/`; documented protocol, denominators, coverage, negative comparison, and limitations.
- **Known risks/regressions/blockers:** Synthetic masks encode predefined scenario-to-channel relationships, not production visual labels. Non-overlapping complete windows cover 90 of 108 held-out runs. DIP-P1's false-positive rate is materially higher. No detector, RCA/RAG, tools, persistence, dashboard, or screenshots yet; no detector/agent metrics are claimed.
- **Next smallest task:** CP-4 detector evaluation; keep the grouped test split untouched when selecting the decision threshold.

### ITERATION 006 - 2026-11-12 - CP-3 region-level evaluation completion

- **Checkpoint:** CP-3 / DIP pipeline
- **Requirement IDs:** G-16, G-17 (DIP evidence), NFR-03, NFR-08, NFR-11
- **Change summary and reason:** Closed the acceptance gap for component-level quality by adding one-to-one predicted/ground-truth region matching at the configured IoU threshold, explicit region-count denominators, and per-window region metrics. The acceptance audit found pixel scores alone were insufficient for the specified pixel/region evaluation.
- **Files created/modified/deleted:** Updated `src/datagard/config.py`, `src/datagard/contracts.py`, `src/datagard/dip/{processor.py,evaluation.py}`, `tests/test_dip.py`, `configs/default.yaml`, `docs/evaluation_protocol.md`, and `ACTION.md`.
- **Existing logic reused:** CP-3 connected-component labels already produced by the sole DIP processor; existing held-out windows, masks, and metric outputs.
- **New logic added (why it is not duplicative):** Region IoU matching is a distinct evaluation calculation in `dip/evaluation.py`; the processor remains the only image-component extraction owner.
- **Tests/commands run:** `uv run pytest -q`; `uv run python -m datagard.visual_inspection`; `python3 -m compileall -q src tests`; `git diff --check`.
- **Results:** PASS - 12 tests passed. Region-level at IoU ≥ 0.5: DIP-B0 TP=22, FP=18, FN=1, 23 GT regions, region F1=0.6984, mean matched IoU=0.8806; DIP-P1 TP=1, FP=18, FN=22, region F1=0.0476, mean matched IoU=1.0000 (one matched region). Pixel metrics remain unchanged and CSV/JSON outputs include denominators.
- **Config/data/schema/docs changed:** Added the region-match threshold to central config and documented the matching method, scores, coverage and limitations. Refreshed artifacts under `artifacts/fingerprints/` and `artifacts/evaluation/dip/`.
- **Known risks/regressions/blockers:** DIP-P1 performs materially worse on both pixel and component recovery; the negative result is retained. Synthetic pixel/channel ground truth remains a limitation. Downstream workflow and presentation checkpoints remain outstanding.
- **Next smallest task:** CP-4 detector evaluation using a separate train/validation/test group split; the existing test split remains untouched for DIP.

### ITERATION 007 - 2026-11-12 - CP-4 anomaly detection and measured ablation

- **Checkpoint:** CP-4 / anomaly detection
- **Requirement IDs:** G-05, G-17, NFR-03, NFR-08, NFR-09, NFR-12
- **Change summary and reason:** Completed a configured Isolation Forest detector and severity rule baseline, grouped train/validation/test evaluation, validation-only threshold selection, test metrics and matched structured-versus-DIP feature ablation. Regenerated all results from the deterministic synthetic dataset.
- **Files created/modified/deleted:** Added/updated detector evaluation implementation and tests from this checkpoint: `src/datagard/{detection.py,evaluation.py,splits.py}`, `src/datagard/dip/region_features.py`, `src/datagard/features.py`, `src/datagard/config.py`, `src/datagard/contracts.py`, `configs/default.yaml`, `tests/test_detection.py`; updated `pyproject.toml`, `uv.lock`, `docs/decisions.md`, `docs/evaluation_protocol.md`, `README.md`, and `ACTION.md`.
- **Existing logic reused:** CP-2 quality rules and canonical feature builder; CP-3 DQF encoder, processor, artifacts and grouped DIP split utilities; CP-1 synthetic truth and incident-group IDs.
- **New logic added (why it is not duplicative):** `detection.py` owns anomaly scoring; `evaluation.py` owns benchmark aggregation/threshold selection; `splits.py` owns group partitioning and is shared with DIP. DIP region features are a configured input to the existing canonical feature builder, not a second detector.
- **Tests/commands run:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q`; `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run python -m datagard.evaluation`.
- **Results:** PASS - 16 tests passed. Test set: 72 runs (42 positive, 30 negative). Rule baseline TP=28 FP=0 FN=14 TN=30, F1=0.8000. Structured Isolation Forest TP=41 FP=29 FN=1 TN=1, F1=0.7321, AP=0.5915. On the matched 43-run subset, structured-only F1=0.7887/AP=0.7637 (TP=28 FP=15 FN=0 TN=0); adding DIP features gives F1=0.8615/AP=0.6725 (TP=28 FP=9 FN=0 TN=6). A single deprecation warning from Starlette TestClient remains.
- **Config/data/schema/docs changed:** Detector/split parameters are in `configs/default.yaml`. Added the exact denominators, metrics, protocol, environment and tradeoff to `docs/evaluation_protocol.md`; README now documents the CP-4 run command. Saved outputs are under ignored `artifacts/evaluation/detection/` and fitted models under `artifacts/models/`.
- **Known risks/regressions/blockers:** Dataset is synthetic and the test scenario mix has only 30 negatives. Full structured detector has only one true negative. The matched ablation set is smaller than the all-test set; DIP improves thresholded F1 but reduces AP, so no general ranking improvement is claimed. MTTD is not measured because this is run-level, not streaming evaluation.
- **Next smallest task:** CP-5 incident service, ranked evidence-grounded RCA hypotheses, and deterministic local runbook retrieval with source references.

### ITERATION 008 - 2026-11-12 - CP-5 incident investigation and local RAG

- **Checkpoint:** CP-5 / incident + RCA + RAG
- **Requirement IDs:** G-04, G-06, G-07, G-09, NFR-02, NFR-03, NFR-08, NFR-12
- **Change summary and reason:** Added in-memory incident deduplication keyed by pipeline/run/family; ranked RCA hypotheses grounded in rule findings, schema diffs, lineage, recent history and optional DIP regions; deterministic local Markdown chunk retrieval; and seven operational runbooks. RCA consumes no synthetic truth labels and returns inconclusive/no hypothesis when evidence is insufficient.
- **Files created/modified/deleted:** Added `src/datagard/{incidents.py,rca.py,rag.py}`, `tests/test_incidents_rca_rag.py`, seven `data/runbooks/*.md` files; updated `src/datagard/{contracts.py,config.py}`, `configs/default.yaml`, `README.md`, `docs/decisions.md`, `docs/evaluation_protocol.md`, and `ACTION.md`.
- **Existing logic reused:** CP-2 `quality.py` finding IDs; CP-1 canonical runs and `SchemaRegistry.diff`/`LineageGraph`; CP-3 mapped DIP regions; CP-4 detector outputs.
- **New logic added (why it is not duplicative):** `incidents.py` is the lifecycle/dedup owner; `rca.py` alone ranks cause hypotheses; `rag.py` alone chunks and retrieves runbook sections. No quality rules or detector scoring were copied.
- **Tests/commands run:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q tests/test_incidents_rca_rag.py`.
- **Results:** PASS - 4 targeted tests passed, covering idempotent incident keys, five structured cause families, runtime history comparison, incomplete telemetry/inconclusive handling, visual evidence wording, and stable schema-drift retrieval.
- **Config/data/schema/docs changed:** Added central `rca.runtime_spike_ratio`, retrieval corpus path and top-k settings. Added ADR-007 and documented the local lexical tradeoff. Retrieval quality/groundedness remains unmeasured; local incident state awaits SQLite in CP-7.
- **Known risks/regressions/blockers:** TF-IDF retrieval is lexical and can miss paraphrases. RCA rules are deterministic and may return multiple plausible hypotheses. In-memory incidents do not survive process restarts yet.
- **Next smallest task:** CP-6 typed tool registry and single orchestrator for inspect, runbook retrieval, quarantine, simulated rerun, approval/escalation, and verification.

### ITERATION 009 - 2026-11-12 - CP-6 guarded closed-loop workflow

- **Checkpoint:** CP-6 / agent closed loop
- **Requirement IDs:** G-08, G-10, G-11, G-12, NFR-04, NFR-05, NFR-08, NFR-12
- **Change summary and reason:** Added one explicit state-machine owner, a typed allowlisted tool registry, proposal planning, configured approval enforcement, simulated quarantine/rerun/schema-alignment, audit events, and post-action quality/trust verification. Source run records are immutable; schema-aligned output is written as a separate local JSON artifact. Quarantine release requires a passing verified output linked to the same incident.
- **Files created/modified/deleted:** Added `src/datagard/{agent.py,tools.py}`, `tests/test_agent_tools.py`; updated `src/datagard/{contracts.py,config.py}`, `configs/default.yaml`, `README.md`, `docs/decisions.md`, `docs/evaluation_protocol.md`, and `ACTION.md`.
- **Existing logic reused:** CP-5 incident service/RCA/retriever, CP-2 quality evaluator, CP-1 canonical schema/run contracts, CP-0 central logging, and validated settings.
- **New logic added (why it is not duplicative):** `agent.py` alone coordinates and transitions state; `tools.py` is the only action boundary; `quality.py` is reused to verify outputs.
- **Tests/commands run:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q tests/test_agent_tools.py`.
- **Results:** PASS - 4 targeted tests passed for typed actions, incident inspection, idempotent quarantine, cleanly isolated rerun, failed rerun verification, high-risk approval bypass and wrong-role rejection, separate repair artifact, original preservation, verification and release.
- **Config/data/schema/docs changed:** Added configured approval-required tool, reviewer role and action artifact directory; documented ADR-008 and workflow evidence. Action and transition audits currently remain in memory until CP-7.
- **Known risks/regressions/blockers:** The synthetic canonical run contains aggregate telemetry, not original row-level tables; therefore the only repair simulation aligns schema metadata. Reruns copy telemetry and may correctly fail verification. No external scheduler or destructive action exists.
- **Next smallest task:** CP-7 SQLite repositories and FastAPI routes for runs, incidents, investigation, actions, approvals and timeline, with persistence across application restarts.

### ITERATION 010 - 2026-11-12 - CP-7 SQLite-backed API

- **Checkpoint:** CP-7 / persistence and FastAPI
- **Requirement IDs:** G-13, G-14, G-15, NFR-04, NFR-06, NFR-08, NFR-09, NFR-12
- **Change summary and reason:** Added a configured local SQLite JSON-record store, application composition service, restart restoration for runs/incidents/tool and agent state, and thin API routes for demo data, pipelines/runs, analysis, incidents, investigation, approval, action execution, timelines, dashboard summary and evaluation summary.
- **Files created/modified/deleted:** Added `src/datagard/{persistence.py,application.py,api.py}`, `tests/test_persistence_api.py`; updated `src/datagard/{main.py,config.py,contracts.py,incidents.py,tools.py,agent.py}`, `configs/default.yaml`, `README.md`, `docs/decisions.md`, `docs/evaluation_protocol.md`, and `ACTION.md`.
- **Existing logic reused:** CP-6 orchestrator/tool registry; CP-5 incident/RCA/retriever; CP-2 quality evaluator; CP-1 generator and canonical contracts; CP-0 FastAPI composition and logging.
- **New logic added (why it is not duplicative):** `persistence.py` solely owns SQLite record operations; `application.py` composes use cases; `api.py` validates and delegates without implementing rules or state transitions.
- **Tests/commands run:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q`; `python3 -m compileall -q src tests`; `git diff --check`.
- **Results:** PASS - 27 tests passed. Integration verifies 360 run records, analyzed incident, investigation, quarantine/rerun, persisted timeline and state across a new app instance; separate integration restores pending approval, repairs schema in a separate artifact, verifies, and resolves after releasing trust. One Starlette/HTTPX deprecation warning.
- **Config/data/schema/docs changed:** Added configured SQLite path; no dependency was added. ADR-009 documents the stdlib SQLite JSON-record tradeoff; README documents startup seeding/API flow.
- **Known risks/regressions/blockers:** Single-process local SQLite is suitable for this prototype but not a multi-instance production service. The store uses typed entity-kind records with JSON payloads instead of normalized columns. No external services are invoked.
- **Next smallest task:** CP-8 Streamlit dashboard that calls FastAPI and visibly demonstrates DQF stages, evidence-based investigation and action/approval workflow.

---

## Entry template

Copy this for each meaningful iteration; fill it with verified facts.

```text
### ITERATION NNN - YYYY-MM-DD - Short name

- Checkpoint:
- Requirement IDs:
- Change summary and reason:
- Files created/modified/deleted:
- Existing logic reused:
- New logic added (why it is not duplicative):
- Tests/commands run:
- Results: PASS / FAIL / NOT RUN (reason)
- Config/data/schema/docs changed:
- Known risks/regressions/blockers:
- Next smallest task:
```

### ITERATION 011 - 2026-11-12 - CP-8 live dashboard evidence

- **Checkpoint:** CP-8 / Streamlit API-client dashboard and genuine captures
- **Requirement IDs:** G-13, G-14, G-15, G-16, NFR-04, NFR-06, NFR-08, NFR-12
- **Change summary and reason:** Completed the API-only Streamlit dashboard with overview, DQF processing, incident investigation, actions/approvals, and evaluation views. Captured the live local UI for the three requested demonstrations: DQF processing stages, incident investigation, and action/approval workflow.
- **Files created/modified/deleted:** Added/updated `dashboard/app.py`, `src/datagard/api.py`, `tests/test_dashboard.py`, and screenshots under `output/dashboard_screenshots/`; updated README, evaluation documentation, and this ledger.
- **Existing logic reused:** FastAPI application services, quality engine, DQF/processor, investigation/RCA/RAG, and orchestrator/tool state.
- **New logic added (why it is not duplicative):** Thin API-client presentation code and a safe artifact-ID/stage allowlist for serving image stages; the dashboard does not query SQLite or implement state transitions.
- **Tests/commands run:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q`.
- **Results:** PASS - final full suite passed 28 tests. Genuine browser screenshots were reviewed and saved for all three required views.
- **Config/data/schema/docs changed:** Dashboard API base URL is configured; screenshot evidence paths and workflow are documented. No new dependency or external connector was added.
- **Known risks/regressions/blockers:** Screens demonstrate a local synthetic app only. They are not production UI evidence or measured model results.
- **Next smallest task:** CP-9 operational evaluation of fixed retrieval/RCA/safety cases and coherent publication artifacts.

### ITERATION 012 - 2026-11-12 - CP-9 operational measurements, report, and merged presentation

- **Checkpoint:** CP-9 / measured evaluation and release evidence
- **Requirement IDs:** G-05, G-06, G-07, G-11, G-16, G-17, NFR-03, NFR-08, NFR-09, NFR-12
- **Change summary and reason:** Saved fixed-case operational evaluations for retrieval, RCA, and policy rejection; reconciled the IEEE manuscript against saved detector/DIP/operational outputs; combined the SIH deck with measured prototype evidence and the three genuine dashboard captures. Removed obsolete stack/benchmark claims from the ending slides and corrected the retained DIP method parameters.
- **Files created/modified/deleted:** Added `src/datagard/operational_evaluation.py`, `output/DataGuard_AI_SIH_Integrated_v5.pptx`, screenshot/build validation artifacts; updated `output/DataGuard_AI_IEEE.tex`, `docs/evaluation_protocol.md`, `README.md`, and this ledger.
- **Existing logic reused:** Existing local TF-IDF retriever, RCA hypotheses, typed action policy, saved detection/DIP evaluation pipeline, and the user-supplied SIH deck’s first five narrative slides.
- **New logic added (why it is not duplicative):** A fixed-case evaluator records operational scores and per-case CSVs using existing services; no duplicate retrieval, RCA, or policy logic was introduced. The report and deck consume persisted outputs rather than inventing figures.
- **Tests/commands run:** `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q`; `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run python -m datagard.operational_evaluation`; Artifact Tool package/layout/first-party import validation; `git diff --check`.
- **Results:** PASS - 28 tests passed (one upstream Starlette TestClient deprecation warning). Detection test n=72, F1=0.732/AP=0.591; matched structured+DIP n=43, F1=0.862/AP=0.673. DIP-B0 pixel F1=0.779/IoU=0.638 versus DIP-P1 F1=0.324/IoU=0.194 on 1,024 valid pixels. Retrieval hit@3=6/7 and MRR=0.857; RCA top-1=4/5/top-3=5/5; safety probes rejected 3/3. Combined deck has 11 slides and passed structural, layout, font-policy, and Artifact Tool import checks. Local LaTeX compilation was stopped at the user's direction; the IEEE source will be compiled in Overleaf.
- **Config/data/schema/docs changed:** Measurements are saved under `artifacts/evaluation/operations/`; paper/deck report denominators and synthetic-set limits. The combined deck retains the SIH narrative and adds current implementation, results, screenshots, and limitations.
- **Known risks/regressions/blockers:** All evaluation data are synthetic; operational sets are small and handcrafted; MTTD/end-to-end latency are unmeasured. No real external connector is invoked.
- **Next smallest task:** Course review and, when available, evaluation on independently labeled real or approved production-like incidents.

### ITERATION 013 - 2026-11-12 - Final handoff audit

- **Checkpoint:** CP-9 / handoff verification
- **Requirement IDs:** G-13, G-15, NFR-08, NFR-12
- **Change summary and reason:** Reconciled README handoff text with the 11-slide final merged deck, corrected links to the repository's `Legacy_Docs_Imp/` architecture and ledger files, and moved superseded generated deck revisions out of `output/` so the final deliverable is unambiguous.
- **Files created/modified/deleted:** Updated `README.md`; moved superseded generated presentations into `.presentation_build/superseded_outputs/`; no application code changed.
- **Existing logic reused:** Existing tested `datagard` package and current final presentation/evaluation artifacts.
- **New logic added (why it was not duplicative):** No runtime logic added.
- **Tests/commands run:** `git diff --check`; live startup command `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run uvicorn datagard.main:app --app-dir src --host 127.0.0.1 --port 8000` reached application startup, then could not bind because the sandbox denies localhost sockets.
- **Results:** Documentation/link audit PASS. `README.md`'s module names match `src/datagard`. The local UI server is not left running; the saved genuine captures and previously passing 28-test suite remain the presentation/workflow evidence.
- **Config/data/schema/docs changed:** README output references now identify the integrated deck, IEEE source, evaluation protocol, architecture report, and append-only ledger correctly.
- **Known risks/regressions/blockers:** This sandbox prevents live localhost serving, so runtime screenshots were not recaptured in this audit. Screenshots on disk were captured from the earlier live local app. LaTeX compilation is left for Overleaf at the user's direction.
- **Next smallest task:** Present the prototype for course review; expand validation with additional seeds and approved real or production-like data.

### ITERATION 014 - 2026-11-12 - Final deck claim audit

- **Checkpoint:** CP-9 / final presentation fidelity
- **Requirement IDs:** G-13, G-15, G-16, G-17, NFR-08, NFR-12
- **Change summary and reason:** Audited every slide's text against current implementation and removed a stale “six typed tools” count from the retained architecture slide. The final deck now says “typed tools (simulated)” without an unsupported operation count.
- **Files created/modified/deleted:** Added `output/DataGuard_AI_SIH_Integrated_v5.pptx`; moved the superseded v4 deck to `.presentation_build/superseded_outputs/`; updated README and this ledger.
- **Existing logic reused:** User SIH deck architecture slide and the current typed tool registry.
- **New logic added (why it was not duplicative):** No runtime logic added; this is a claim correction in presentation content.
- **Tests/commands run:** Artifact Tool finalization package integrity, geometry/font policy, first-party import; rendered and inspected changed slide 4; extracted final PPTX slide text and checked obsolete claim removal.
- **Results:** PASS - 11 slides; package integrity and layout findings zero; first-party import passed. Slide 4 now accurately describes typed simulated actions without an outdated count.
- **Config/data/schema/docs changed:** README points to v5; source SIH copy and its original problem/solution flow remain preserved.
- **Known risks/regressions/blockers:** Locally launched UI serving remains disallowed by the sandbox; saved screenshots are genuine from the earlier live app. Overleaf compilation remains user-directed.
- **Next smallest task:** Course review.

### ITERATION 015 - 2026-11-12 - Submission package and repository link audit

- **Checkpoint:** CP-9 / submission handoff
- **Requirement IDs:** G-13, G-15, G-16, G-17, NFR-08, NFR-12
- **Change summary and reason:** Added the supplied compiled IEEE paper PDF to `output/`, added the course Drive folder and direct GitHub artifact links to the README, and checked the paper/deck against the submission checklist. Relocated `ACTION.md` to the repository root and `AGENTS.md` to `Legacy_Docs_Imp/` without changing their contents before this ledger entry.
- **Files created/modified/deleted:** Added `output/23cd3049_23cd3001_DataGuardAI.pdf`; updated `README.md` and this ledger; moved `Legacy_Docs_Imp/ACTION.md` to `ACTION.md` and `AGENTS.md` to `Legacy_Docs_Imp/AGENTS.md`.
- **Existing logic reused:** Existing compiled paper, final 11-slide deck, saved synthetic evaluation outputs, and course submission checklist supplied by the user.
- **New logic added (why it was not duplicative):** No application logic added. The README is an index to the existing code, evidence, and submission materials.
- **Tests/commands run:** `pdfinfo` on the supplied and repository PDF; bundled `pdftoppm` rendered all four pages for visual inspection; PDF SHA-256 comparison; PPTX ZIP integrity and 11-slide content inspection.
- **Results:** PASS - PDF is four pages, Letter size, unencrypted, and visually readable with no obvious clipping; copied file hash matches the supplied PDF. PPTX is structurally intact and includes the flow, implementation, measured results, and dashboard screenshots.
- **Config/data/schema/docs changed:** README now includes the provided Drive link and direct GitHub links to source, report, datasets, metrics, masks, tests, and screenshots. It records the four-page PDF as present and the group-upload filename prefix as a form-specific final step.
- **Known risks/regressions/blockers:** Dataset and all measured evaluations are synthetic/small as disclosed. Optional deck slide numbering skips from 04 to 08 and repeats 10 on the dashboard slides. Apply the required student-name/roll-number prefix on files uploaded through each student's form.
- **Next smallest task:** Submit the four-page PDF separately and select no more than ten individually named supporting files; correct deck numbering if time permits.

### ITERATION 016 - 2026-11-12 - DIP-centered presentation and Cambria styling

- **Checkpoint:** CP-9 / final presentation polish
- **Requirement IDs:** G-16, G-17, NFR-08, NFR-12
- **Change summary and reason:** Revised the solution, architecture, method, implementation, and evaluation slides to make DIP's role as the visual-evidence bridge easy to see. The DQF → DIP regions → run/metric mapping is highlighted in the deck's teal visual language inspired by the architecture document. Normalized section labels and applied Cambria to editable text and theme font declarations.
- **Files created/modified/deleted:** Added `output/DataGuard_AI_SIH_Integrated_v6.pptx`; updated `README.md` and this ledger.
- **Existing logic reused:** The existing 11-slide deck, its genuine dashboard captures, current measured DIP outputs, and the architecture document's DQF/DIP workflow.
- **New logic added (why it was not duplicative):** No runtime logic added. Slide styling and wording emphasize the existing encoder, OpenCV processing, traceable region mapping, and measured segmentation trade-offs.
- **Tests/commands run:** LibreOffice PPTX-to-PDF render; reviewed a contact sheet of all 11 slides and full-size renders of changed slides 3-7; verified 11 slides, package integrity, Cambria on 152 editable slide text runs, and Cambria-only typeface declarations in the presentation OOXML.
- **Results:** PASS - visual review shows the DIP card and evidence path clearly, both DIP methods and results remain readable, screenshots remain unchanged, and the section labels follow the deck order. PPTX package integrity passes.
- **Config/data/schema/docs changed:** README now links v6 and records its Cambria usage and rendering caveat. No application behavior or evaluation outputs changed.
- **Known risks/regressions/blockers:** Cambria is not installed in the local renderer, which substitutes another serif font during preview; confirm the final layout in PowerPoint with Cambria available. The genuine dashboard screenshots contain their original UI typography and remain unaltered.
- **Next smallest task:** Open v6 in PowerPoint with Cambria available and complete the name/roll-number file prefixes for submission.


### ITERATION 017 - 2026-11-12 - Evaluation-focused main-branch README

- **Checkpoint:** CP-9 / evaluation handoff documentation
- **Requirement IDs:** G-15, G-16, G-17, NFR-08, NFR-12
- **Change summary and reason:** Prepared an evaluator-oriented README for the `main` branch that presents the implemented workflow, DIP contribution, measured results with denominators, reproducible commands, evidence links, and limitations. The existing collaboration README remains on `dataguardv1`.
- **Files created/modified/deleted:** Updated `README.md` and appended this entry to `ACTION.md`; no source code, data, or measured artifacts changed.
- **Existing logic reused:** Implementation descriptions and metrics were checked against the architecture requirements, evaluation protocol, tracked outputs, and saved project artifacts.
- **New logic added (why it was not duplicative):** No application logic added; documentation was reorganized for academic review and explicit evidence-first interpretation.
- **Tests/commands run:** `git diff --check`; Python Markdown-link target audit; confirmed reported values and denominators against `docs/evaluation_protocol.md` and confirmed linked local files are tracked. No application tests were run because no code changed.
- **Results:** PASS - no whitespace errors or missing local link targets; the displayed metrics/denominators match the evaluation protocol; linked deliverables are present in the branch.
- **Config/data/schema/docs changed:** README and append-only project ledger only.
- **Known risks/regressions/blockers:** The remote had no `main` branch at the start of this iteration; this branch is based on the validated `dataguardv1` snapshot. All reported evaluation remains synthetic, and limits are stated in the README.
- **Next smallest task:** Review the public `main` branch and set the repository default branch to `main` if desired.

### ITERATION 019 - 2026-11-12 - Student-team voice in project README

- **Checkpoint:** CP-9 / evaluation handoff documentation
- **Requirement IDs:** G-15, G-16, G-17, NFR-08, NFR-12
- **Change summary and reason:** Reworded the evaluation README in first-person plural so it reflects our student team's project, implementation, method, evidence, and limitations while retaining the measured figures and cautions.
- **Files created/modified/deleted:** Updated `README.md` and appended this ledger entry; the same README is synchronized to `dataguardv1`. The archived collaboration README remains unchanged.
- **Existing logic reused:** Existing implementation, evaluation protocol, saved results and artifact links.
- **New logic added (why it was not duplicative):** No runtime logic added; only narrative voice changed.
- **Tests/commands run:** `git diff --check`; local link and metric consistency audit; compare root README with the updated `dataguardv1` copy after synchronization.
- **Results:** PASS - 21 local links resolve; reported figures remain unchanged; first-person team voice and scope caveats are present.
- **Config/data/schema/docs changed:** README and append-only project ledger only.
- **Known risks/regressions/blockers:** None identified; evaluation limitations remain explicitly stated.
- **Next smallest task:** None for this README update; both published branches carry the student-team version.
