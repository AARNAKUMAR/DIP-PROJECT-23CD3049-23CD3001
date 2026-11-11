# Architecture decisions

## ADR-001: CP-0 local modular-monolith foundation

- **Status:** Accepted for CP-0
- **Context:** The repository contained requirements, governance documents, an architecture illustration, and an IEEE manuscript, but no application source, tests, package metadata, or measured artifacts.
- **Decision:** Begin with a `src/datagard` Python package, FastAPI composition root, Pydantic Settings backed by `configs/default.yaml` and `DATAGUARD_` environment variables, and standard-library logging configured once at startup. Provide only `/health` in this checkpoint.
- **Requirements:** CP-0, G-13 (health/API foundation only), G-15 (setup foundation only), NFR-01, NFR-02, NFR-07, NFR-08, NFR-09, NFR-12.
- **Dependencies:** FastAPI, Pydantic Settings with YAML support, Uvicorn; pytest and HTTPX for development smoke tests.
- **Alternatives considered:** A standard-library-only HTTP server would avoid dependencies but would diverge from the selected FastAPI/Pydantic stack. A full project scaffold would create unused modules before their checkpoint.
- **Trade-off:** The health endpoint and package establish the runtime boundary, but domain workflows, persistence, metrics, dashboard, and evaluation remain unimplemented until their checkpoints.

## ADR-002: CP-1 deterministic JSONL data boundary

- **Status:** Accepted for CP-1
- **Context:** Later quality, detection, DIP, and agent work needs deterministic labelled run telemetry, while labels must not leak into model input.
- **Decision:** Represent canonical runs and schema fields as strict Pydantic contracts. Generate ten required normal, defect, benign-seasonality, and missing-telemetry scenarios with a configured random seed. Write run inputs and scenario truth to separate JSONL files. Reject malformed source records with file and line context. Keep schema comparison and a small directed lineage graph in `metadata.py`.
- **Requirements:** G-01, G-02, G-15, NFR-03, NFR-04, NFR-08, NFR-09, NFR-12.
- **Dependencies:** No new runtime dependency; JSONL, seeded `random`, and existing Pydantic.
- **Alternatives considered:** CSV would require encoding nested per-field metrics/schema data or splitting the canonical run across multiple tables. SQLite persistence belongs to CP-7. JSONL keeps one versionable record per run and a separate truth file.
- **Trade-off:** The initial generator is small and synthetic, not a production connector. Lineage and schema registry are in-memory until the persistence checkpoint.

## ADR-003: CP-2 single structured quality engine and stable feature vector

- **Status:** Accepted for CP-2
- **Context:** Detection and later DIP work need structured findings and one reproducible ML feature contract; quality rules must not be reimplemented in those modules.
- **Decision:** Implement null, duplicate, row-count, schema, configured range, distribution-baseline, pipeline-status, and missing-telemetry findings in `quality.py`. Keep thresholds/ranges and feature ordering in the validated central YAML settings. Implement `features.py` as the only constructor of the named numeric feature vector.
- **Requirements:** G-03, NFR-02, NFR-03, NFR-08, NFR-12.
- **Dependencies:** No new runtime dependency.
- **Alternatives considered:** Embedding rule checks in ingestion or feature construction would duplicate logic and make quality evidence unavailable to later tools. A model framework is deferred to CP-4.
- **Trade-off:** Distribution findings require an explicit history baseline; the engine omits that finding when no baseline is supplied instead of inventing one.

## ADR-004: CP-3 DIP module ownership

- **Status:** Accepted
- **Context:** The project operating contract names `dip/encoder.py` as the sole fingerprint encoder and `dip/processor.py` as owner of image operations. The architecture report §6.3 and §6.4 instead name `visual_inspection.py` as owner of both. Creating either layout without recording the conflict would violate project governance.
- **Decision:** Follow the explicit operating-contract ownership: `dip/encoder.py` is the sole fingerprint encoder and `dip/processor.py` is the sole image-processing owner. `visual_inspection.py` is permitted only as a thin composition facade that delegates to these modules. The architecture ownership table and target tree were updated to match.
- **Requirements:** G-16, NFR-12.
- **Alternatives considered:** Making `visual_inspection.py` own both operations would contradict the explicit sole-owner rules in the operating contract.
- **Trade-off:** The thin facade adds one import boundary but keeps a single implementation per concern and retains the architecture's application-facing entry point.

## ADR-005: CP-3 classical image-processing dependencies

- **Status:** Accepted for CP-3
- **Context:** G-16 requires calibrated grayscale fingerprints, global/adaptive thresholding, mathematical morphology, connected components, and saved image artifacts. The current project has no array or image-processing runtime dependency.
- **Decision:** Add NumPy for deterministic image arrays and OpenCV's headless Python distribution for the specified classical DIP operators and image output. Use `opencv-python-headless` because the prototype needs image operations but no GUI windowing stack.
- **Requirements:** G-16, NFR-03, NFR-08, NFR-09.
- **Alternatives considered:** Hand-writing morphology and connected components in pure Python would duplicate mature image operators and add correctness risk; Pillow does not provide the required adaptive threshold/morphology/connected-component path without reimplementing those algorithms.
- **Trade-off:** Adds compiled local packages and a larger environment footprint; no external service or model download is required.

## ADR-006: CP-4 Isolation Forest and evaluation dependencies

- **Status:** Accepted for CP-4
- **Context:** G-05 requires a primary Isolation Forest detector, validation-only threshold selection, ranking Average Precision, and a reproducible comparison against a deterministic quality-rule baseline. G-17 also requires a structured versus structured-plus-DIP-region ablation.
- **Decision:** Add scikit-learn for `IsolationForest`, `StandardScaler`, confusion metrics, and Average Precision; use joblib to save the trained local model artifacts. Fit scaler and models only on clean training-group runs; choose the anomaly-score threshold on validation groups by maximum F1; evaluate once on untouched test groups. Record the exact split IDs, threshold, parameters, prediction rows, denominators, and confusion matrices. Compare DIP ablation models only over the identical subset for which a causal 30-run window exists, using the CP-3 selected Otsu segmentation outputs.
- **Requirements:** G-05, G-17, NFR-03, NFR-04, NFR-08, NFR-09, NFR-11.
- **Dependencies:** `scikit-learn` and direct `joblib` usage.
- **Alternatives considered:** Implementing Isolation Forest and Average Precision manually would create correctness and maintenance risk. A neural detector or external tracking service adds infrastructure not justified by this local synthetic benchmark.
- **Trade-off:** The model score is not a calibrated probability. The synthetic benchmark and small grouped sample do not establish production performance; thresholds and test outcomes must be reported with their denominators.

## ADR-007: CP-5 local evidence-grounded investigation

- **Status:** Accepted for CP-5
- **Context:** Incident creation, RCA, and runbook retrieval must work locally without making an LLM/provider or external vector service a core dependency.
- **Decision:** Deduplicate incidents by pipeline, affected run, and family using detector predictions and structured findings. Rank typed RCA hypotheses from findings, registered-versus-observed schema diff, supplied run history, lineage, and optional DIP region references. Use local Markdown runbooks split into stable heading sections and rank them with deterministic TF-IDF cosine similarity; configure corpus path and top-k centrally.
- **Requirements:** G-04, G-06, G-07, G-09, NFR-02, NFR-03, NFR-08, NFR-12.
- **Dependencies:** No additional dependency; standard-library tokenization and scoring are sufficient for the bounded corpus.
- **Alternatives considered:** Downloaded sentence-transformer embeddings provide semantic matching but add a model artifact/network/bootstrap requirement. An external vector store is unnecessary for seven curated local runbooks. A lexical TF-IDF path is selected as the deterministic local implementation and fallback.
- **Trade-off:** Lexical retrieval may miss paraphrases and needs a later measured relevance/groundedness evaluation. Incident state is currently in memory and will be persisted in CP-7.

## ADR-008: CP-6 registered local actions and human approval

- **Status:** Accepted for CP-6
- **Context:** The closed loop must demonstrate state changes and approval without executing production actions or allowing planner-supplied code/paths.
- **Decision:** `agent.py` is the sole state-transition owner. `tools.py` exposes one typed allowlist for inspection, retrieval, quarantine, simulated rerun, isolated schema alignment, approval, escalation, and verified release from quarantine. Tool schemas, risk, preconditions, idempotency, side effects and failure modes are inspectable. Approval-required tools and approver role are configured centrally. Only the deterministic `align_schema` simulation is implemented; it writes a separate JSON artifact, leaves the original unchanged, and must pass configured quality verification before release.
- **Requirements:** G-08, G-10, G-11, G-12, NFR-04, NFR-05, NFR-08, NFR-12.
- **Dependencies:** No new dependencies.
- **Alternatives considered:** Real scheduler, database, or data-platform calls violate the local-prototype scope. A free-form repair tool would accept unbounded transformation instructions; only one explicit schema operation is allowed.
- **Trade-off:** Audit/state is in memory until CP-7. The simulation operates on canonical run metadata, not row-level production data; rerun verification honestly retains unresolved findings when the copied telemetry still fails.

## ADR-009: CP-7 standard-library SQLite persistence and thin API

- **Status:** Accepted for CP-7
- **Context:** Runs, findings, incidents, action plans, approvals, tool audits, transitions and outcomes need restart persistence without introducing infrastructure.
- **Decision:** Use Python's built-in `sqlite3` through one `SQLiteStore` owner. Store strict domain records as JSON payloads keyed by an enumerated entity type and stable domain ID. Compose services once into `ApplicationServices`; HTTP routes in `api.py` validate transport requests and delegate. The store path is configured centrally. Existing in-memory tool and agent snapshots are restored from SQLite at application startup.
- **Requirements:** G-13, G-14, G-15, NFR-04, NFR-06, NFR-08, NFR-09, NFR-12.
- **Dependencies:** No new package; `sqlite3` ships with Python.
- **Alternatives considered:** SQLAlchemy would add a package and mapping layer without current multi-database needs. Separate database tables for every typed entity are a future migration option; a constrained local prototype can use stable typed identifiers and strict Pydantic serialization in one record table.
- **Trade-off:** JSON-record persistence is less queryable than normalized relational columns. SQLite remains local and single-process; state survives restarts and can be migrated to normalized tables if query needs grow.

## ADR-010: CP-8 Streamlit API-client dashboard

- **Status:** Accepted for CP-8
- **Context:** G-13 and G-16 require a usable investigation surface that demonstrates actual DQF inputs/intermediates and the guarded action workflow.
- **Decision:** Add Streamlit as the local dashboard runtime. The dashboard uses HTTP calls to FastAPI only; it does not import application/domain services, query SQLite, calculate metrics, or perform actions directly. Add constrained FastAPI artifact endpoints that resolve only known DQF artifact IDs and an enumerated set of stage names.
- **Requirements:** G-13, G-16, G-17, NFR-02, NFR-08, NFR-09, NFR-12.
- **Dependencies:** Add Streamlit as a runtime dependency to serve a local interactive dashboard. `urllib` from the standard library handles API calls, avoiding a separate HTTP-client dependency.
- **Alternatives considered:** A static HTML mock would not demonstrate live API state or action/approval flow. A custom frontend framework adds build tooling and a second UI stack. Serving local files directly from Streamlit would violate the API-client boundary.
- **Trade-off:** Streamlit is suitable for this academic local prototype but has less UI control than a dedicated frontend. Screenshots must come from the running app with API-backed content.
