# DataGuard AI

**Agentic Data-Quality Incident Detection, Root-Cause Analysis and Guarded Remediation**<br>
**Project ID:** HSR-AGAI-001 · **DIP integration:** Digital Image Processing-Based Visual Data-Quality Inspection

## Our team

| Student | Roll number | Email | Department | Institute |
|---|---|---|---|---|
| Tishya Jha | 23CD3049 | [23cd3049@rgipt.ac.in](mailto:23cd3049@rgipt.ac.in) | Computer Science and Design Engineering | Rajiv Gandhi Institute of Petroleum Technology |
| Aarna Kumar | 23CD3001 | [23cd3001@rgipt.ac.in](mailto:23cd3001@rgipt.ac.in) | Computer Science and Design Engineering | Rajiv Gandhi Institute of Petroleum Technology |

We developed DataGuard AI as a reproducible, local-first prototype for investigating unreliable data-pipeline runs. Our workflow combines structured quality rules, anomaly detection, evidence-grounded root-cause hypotheses, local runbook retrieval, guarded simulated actions, human approval for higher-risk repair, and post-action verification.

We made Digital Image Processing (DIP) a central perception contribution: our prototype encodes canonical telemetry as a Data Quality Fingerprint (DQF), processes it with classical image operations, and maps segmented regions back to run and metric evidence. DIP complements our structured quality checks; it does not replace them or infer causes by itself.

> **Telemetry → DQF image → DIP regions → mapped run/metric evidence → investigation → guarded action → verification**

## Evaluation snapshot

We report the measurements below from our saved synthetic evaluation artifacts and document the protocols in [our evaluation report](docs/evaluation_protocol.md). We include each denominator because our evaluation partitions differ by track.

| Evaluation track | Dataset / denominator | Result | Interpretation |
|---|---:|---|---|
| Structured Isolation Forest | Held-out test: 72 runs (42 incidents, 30 non-incidents) | F1 **0.7321**, average precision **0.5915** | At the selected validation threshold: TP 41, FP 29, FN 1, TN 1. The small, synthetic scenario mix creates many false positives. |
| Structured + DIP feature ablation | Matched held-out subset: 43 runs (28 incidents, 15 non-incidents) | F1 **0.8615**, average precision **0.6725** | Versus structured-only on the same subset, false positives fell from 15 to 9; AP also fell from 0.7637 to 0.6725. This is a threshold-specific trade-off, not evidence of general ranking improvement. |
| DIP segmentation: global Otsu (DIP-B0) | 1,024 valid pixels in 3 held-out fingerprints; 90 positive pixels | Pixel F1 **0.7792**, IoU **0.6383** | 90 TP, 51 FP, 0 FN, 883 TN. All 56 invalid/missing cells are excluded. |
| DIP segmentation: adaptive threshold + closing (DIP-P1) | Same 1,024 valid pixels | Pixel F1 **0.3243**, IoU **0.1935** | 90 TP, 375 FP, 0 FN, 559 TN; the alternative underperforms the Otsu baseline on this benchmark. |
| Runbook retrieval | 7 fixed canonical queries | hit@3 **6/7**, MRR **0.857** | One query is missed; this small hand-authored set does not estimate general retrieval quality. |
| RCA ranking | 5 fixed synthetic cases | top-1 **4/5**, top-3 **5/5** | Case-level functional evidence only. |
| Action-policy probes | 3 invalid/unauthorized requests | rejected as expected **3/3** | These probes do not establish policy accuracy for arbitrary requests. |

We generated the scenarios synthetically; they are not externally collected production incidents. Our evaluation is small and run-level, so we have **not measured** mean time to detect (MTTD) or end-to-end service latency. We document methods, exact split/coverage, limitations, and per-case results in [`docs/evaluation_protocol.md`](docs/evaluation_protocol.md) and save the outputs under `artifacts/evaluation/`.

## What we implemented

- **Data and quality:** We generated deterministic synthetic pipeline runs with separate truth labels and implemented strict JSONL input, schema and lineage metadata, one structured quality engine, and a canonical feature vector.
- **DIP:** We implemented calibrated DQF encoding with a validity mask and saved axis mappings; OpenCV-based global Otsu and adaptive/morphological methods; connected-region extraction; run/metric mapping; ground-truth comparison; and saved masks, overlays, and metrics.
- **Detection and investigation:** We added an Isolation Forest and severity-rule baseline, incident deduplication, evidence-based RCA hypotheses using findings/history/schema/lineage, and local TF-IDF retrieval over seven Markdown runbooks.
- **Guarded response:** We built one orchestrator and typed tool registry for simulated quarantine/rerun, approval-gated schema-alignment simulation, isolated output artifacts, post-action quality verification, and an audit trail.
- **Persistence and interface:** We use SQLite persistence across application restarts, FastAPI routes, and an interactive API-backed Streamlit dashboard with overview, DQF, investigation, action/approval, and evaluation views.
- **Reproducibility:** We keep configuration in `configs/default.yaml`, tests in `tests/`, and evaluation outputs and genuine UI captures in the repository.

We do not call a production database, scheduler, cloud connector, or external LLM service. We simulate remediation locally and preserve source run records.

## Our method at a glance

1. We generate deterministic pipeline-run telemetry and keep scenario truth separate from model inputs.
2. We apply structured quality rules and construct canonical model features.
3. We encode a fixed telemetry window as a DQF image, preserve run/channel axis metadata, and mark missing cells invalid.
4. We segment the image using DIP-B0 and DIP-P1, map connected regions back to telemetry, and score against synthetic ground-truth masks.
5. We combine detector decisions and structured/DIP evidence to create incidents, rank RCA hypotheses, and retrieve relevant runbook sections.
6. We plan only allowlisted typed actions, enforce preconditions and approval server-side, then verify and persist simulated outcomes.

We describe the full workflow and module boundaries in [`Legacy_Docs_Imp/ARCHITECTURE_AND_REQUIREMENTS.md`](Legacy_Docs_Imp/ARCHITECTURE_AND_REQUIREMENTS.md). In our design, DIP supplies evidence; it does not duplicate the quality-rule or RCA engines or act autonomously.

## Run locally

To run our prototype, install Python 3.11+ and `uv`.

```bash
uv sync --extra dev
uv run uvicorn datagard.main:app --app-dir src --reload
```

- Health check: `http://127.0.0.1:8000/health`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Start the dashboard in a second terminal: `uv run streamlit run dashboard/app.py`
- Run tests: `uv run pytest -q`

When we start the API with an empty store, it initializes the configured SQLite database and deterministic input data. We can regenerate the data and evaluation artifacts with:

```bash
uv run python -m datagard.ingestion
uv run python -m datagard.visual_inspection
uv run python -m datagard.evaluation
uv run python -m datagard.operational_evaluation
```

We use group-separated partitions for detection and DIP evaluation. Our DIP benchmark fits channel baselines on clean training runs and reports only complete held-out windows and valid pixels. We save configuration, split IDs, predictions, and confusion matrices with the outputs; please consult our protocol when interpreting the comparisons.

## Project evidence from our work

- **Four-page IEEE conference paper (PDF):** [`output/23cd3049_23cd3001_DataGuardAI.pdf`](output/23cd3049_23cd3001_DataGuardAI.pdf) · editable source: [`output/DataGuard_AI_IEEE.tex`](output/DataGuard_AI_IEEE.tex)
- **Presentation:** [`output/DataGuard_AI_SIH_Integrated_v6.pptx`](output/DataGuard_AI_SIH_Integrated_v6.pptx), an 11-slide project narrative with genuine dashboard captures.
- **Evaluation methods and measured results:** [`docs/evaluation_protocol.md`](docs/evaluation_protocol.md)
- **DIP outputs:** [`artifacts/evaluation/dip/`](artifacts/evaluation/dip/) and [`artifacts/fingerprints/`](artifacts/fingerprints/)
- **Detection outputs:** [`artifacts/evaluation/detection/`](artifacts/evaluation/detection/)
- **RCA, retrieval, and policy case outputs:** [`artifacts/evaluation/operations/`](artifacts/evaluation/operations/)
- **Dashboard screenshots:** [DQF processing](output/dashboard_screenshots/dqf_processing.png) · [incident investigation](output/dashboard_screenshots/incident_investigation.png) · [actions and approvals](output/dashboard_screenshots/actions_approvals.png)
- **Source code:** [`src/datagard/`](src/datagard/) · [`dashboard/`](dashboard/) · [`tests/`](tests/)
- **Data and labels:** [`artifacts/data/pipeline_runs.jsonl`](artifacts/data/pipeline_runs.jsonl) · [`artifacts/data/scenario_truth.jsonl`](artifacts/data/scenario_truth.jsonl)
- **Iteration history:** [`ACTION.md`](ACTION.md) · **design decisions:** [`docs/decisions.md`](docs/decisions.md)

## Scope and limitations

We built and evaluated this academic local prototype using deterministic synthetic data. Our labels derive from predefined injected scenarios, so the results do not establish accuracy on independently labeled production data. Our fixed retrieval, RCA, and policy evaluation sets are small. The adaptive DIP alternative performs worse than global Otsu in our reported pixel and region evaluation. Our repair and rerun operations are bounded simulations over canonical run records, not live data-platform operations. The test suite and saved artifacts support reproducibility of our prototype; they do not establish production readiness.

We have also linked our optional submission materials in the [group Google Drive folder](https://drive.google.com/drive/folders/14eESeGpSued7mg_-TGGuvwqHC8BtWPKE?usp=sharing).
