# Evaluation protocol and current measurements

## CP-3 DIP segmentation

The run generator produces ten normal, incident, benign-seasonality, and partial-telemetry scenarios. Each scenario has twelve incident groups of three consecutive runs (360 runs total). Inputs and truth labels are saved separately. The random seed and all image-processing parameters are in `configs/default.yaml`.

Groups are kept intact and divided chronologically: the first 70% of the shuffled, seed-fixed group schedule is training data and the final 30% is held out. DQF channel medians and median absolute deviations are fitted only from clean runs in the training partition. The held-out set contains 108 runs in 36 groups. With a 30-run window and non-overlapping stride of 30, three fingerprints cover 90 runs (83.33%); the remaining 18 held-out runs do not form a complete window and are excluded. The output summary records the split IDs and coverage.

The benchmark compares global Otsu thresholding (DIP-B0) with adaptive Gaussian thresholding followed by configured morphological closing (DIP-P1). Median filtering is disabled because the synthetic telemetry generator does not inject salt-and-pepper pixel noise. Ground-truth masks come from the scenario labels and predeclared affected channels. Missing pixels are excluded from confusion counts using the saved validity mask.

Pixel metrics use all valid cells in each saved fingerprint. Region metrics label predicted and ground-truth components with the configured connectivity and greedily match one-to-one in descending component IoU order at the configured 0.5 minimum. Region precision/recall/F1 use matched, predicted, and ground-truth component counts; mean matched IoU is averaged over true-positive region matches.

### Measured result

Command: `uv run python -m datagard.visual_inspection`

Latest saved run: 90 unique held-out runs covered by three fingerprints; 1,024 valid evaluated pixels, including 90 positive ground-truth pixels. The 56 missing telemetry cells are excluded. Each method is evaluated against the same masks.

| Method | TP | FP | FN | TN | Valid pixels | Precision | Recall | F1 | IoU | Median processing ms/fingerprint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DIP-B0 (global Otsu) | 90 | 51 | 0 | 883 | 1,024 | 0.6383 | 1.0000 | 0.7792 | 0.6383 | 0.3249 |
| DIP-P1 (adaptive + closing) | 90 | 375 | 0 | 559 | 1,024 | 0.1935 | 1.0000 | 0.3243 | 0.1935 | 0.1797 |

Region-level comparison at the configured IoU match threshold of 0.5:

| Method | TP regions | FP regions | FN regions | Predicted regions | Ground-truth regions | Precision | Recall | F1 | Mean matched IoU |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DIP-B0 | 22 | 18 | 1 | 40 | 23 | 0.5500 | 0.9565 | 0.6984 | 0.8806 |
| DIP-P1 | 1 | 18 | 22 | 19 | 23 | 0.0526 | 0.0435 | 0.0476 | 1.0000 |

The current alternative does **not** improve segmentation over the Otsu baseline: both recover all 90 labeled pixels, but DIP-P1 produces substantially more false-positive pixels and only one of 23 ground-truth regions meets the matching criterion. Per-scenario confusion counts, exact runtime medians, software/platform versions, threshold settings, split group IDs, and run-level artifacts are in `artifacts/evaluation/dip/` and `artifacts/fingerprints/`. Runtime varies across executions and is retained from each measured run rather than hard-coded here.

### Limitations

- Ground truth is derived from synthetic injected defects and a predefined pixel-to-channel mapping; it is not a manually labeled production image corpus.
- Non-overlapping complete windows cover 90 of 108 held-out runs. Metrics describe the 1,024 valid pixels in the three evaluated fingerprints, not all held-out telemetry.
- DIP-P1's adaptive threshold and closing are an alternative method, not an empirically superior method. No threshold tuning was performed on the held-out data.
- These measurements concern segmentation only. Detection results are recorded below. MTTD remains unmeasured because there is no streaming alert-time protocol. Retrieval/RCA/policy timings and dashboard evidence are recorded in the operational evaluation section.

## CP-4 anomaly detection

Command: `uv run python -m datagard.evaluation`

### Protocol

The evaluation reuses the deterministic 360-run, 120-incident-group dataset and separates whole groups into 216 training runs, 72 validation runs and 72 test runs. The test partition contains 42 labelled incidents and 30 non-incidents. Isolation Forest and its feature scaler are fitted on 24 clean training runs; thresholds are selected on validation by maximum F1, with ties resolved toward the higher anomaly score. The test partition is evaluated once. Average precision is computed with `sklearn.metrics.average_precision_score`; anomaly scores are ranking scores, not probabilities. The DIP feature ablation uses the same subset of runs with a complete causal fingerprint window: 18 clean training, 43 validation (31 positives), and 43 test (28 positives, 15 negatives). Model parameters, exact split IDs, selected thresholds, environment versions and predictions are in the saved outputs.

### Measured held-out results

| Detector | Test n (positive / negative) | TP | FP | FN | TN | Precision | Recall | F1 | Average precision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Severity rule baseline | 72 (42 / 30) | 28 | 0 | 14 | 30 | 1.0000 | 0.6667 | 0.8000 | N/A (binary rule score) |
| Isolation Forest, structured features | 72 (42 / 30) | 41 | 29 | 1 | 1 | 0.5857 | 0.9762 | 0.7321 | 0.5915 |
| Matched ablation, structured only | 43 (28 / 15) | 28 | 15 | 0 | 0 | 0.6512 | 1.0000 | 0.7887 | 0.7637 |
| Matched ablation, structured + DIP-B0 features | 43 (28 / 15) | 28 | 9 | 0 | 6 | 0.7568 | 1.0000 | 0.8615 | 0.6725 |

On the matched 43-run subset, adding the configured three DIP region features reduces false positives from 15 to 9 and raises thresholded F1 by 0.0728, while average precision declines by 0.0912. This small synthetic test subset shows a threshold-specific tradeoff, not a general ranking improvement. The broader structured model has 29 false positives and only one true negative; this result is sensitive to the scenario mix and is not production evidence. The rule baseline is conservative and high precision but misses 14 of 42 labelled incidents. No MTTD is reported: the current benchmark scores run-level records and does not define a streaming alert timestamp protocol.

### Saved artifacts and environment

`artifacts/evaluation/detection/` contains `detection_metrics.json`, `detection_metrics.csv`, `detection_predictions.csv`, `detection_confusion_matrices.csv`, `detection_scenario_metrics.csv` and `detection_split.json`. Fitted models are saved under `artifacts/models/`. The regenerated run used Python 3.12.13, NumPy 2.5.4 and scikit-learn 1.9.1 on arm64 macOS 26.6.2. Thresholds were selected on validation only; exact values and validation counts are recorded in the JSON summary. Per-scenario predictions expose failure modes, including confusion between benign seasonality and incident labels in this synthetic design.

These are reproducible synthetic benchmark measurements, not claims of production accuracy. The 43-run ablation is restricted to runs covered by complete causal DIP windows; its denominator differs from the all-test structured model. The severity baseline is binary, so average precision is not defined for it.

## CP-5 investigation implementation

`IncidentService` accepts detector decisions and quality findings; it does not read evaluation labels. It groups evidence by cause family and deduplicates on pipeline, affected run, and family. `investigate_run` emits ranked typed hypotheses with finding IDs, schema diff context, lineage nodes, recent-run context, and optional `dip:<method>:<component>` references. A visual region is explicitly described as evidence, not a cause. Missing telemetry without stronger evidence yields `INCONCLUSIVE`; absent evidence yields no unsupported hypothesis. The runtime comparison is enabled only when comparable recent runs and configured `rca.runtime_spike_ratio` are supplied.

`RunbookRetriever` reads curated Markdown from `data/runbooks/`, chunks by heading with stable document/section IDs, and uses deterministic TF-IDF cosine ranking with configured `retrieval.top_k`. Seven runbooks cover schema drift, row-count drop, null surge, duplicate spike, distribution shift, safe rerun, and escalation. Its measured fixed-query ranking and latency are below. The local store restores incident state after application restarts (CP-7).

## CP-6 closed-loop action evidence

`AgentOrchestrator` owns transitions and calls `ToolRegistry` for every tool operation. Registered tools expose typed input/output schemas, risk, preconditions, idempotency behavior, allowed side effects, and failure modes. The high-risk schema simulation requires a recorded approval from the configured `data_engineer` role and an approval ID bound to the exact proposal. It writes `artifacts/actions/<repair-id>.json`; the original run remains unchanged. Batch trust can be restored only after a passing simulated artifact is associated with the same incident. The low-risk rerun creates a separate local run record but copies observed telemetry; if quality findings persist, the workflow escalates and does not claim resolution.

Targeted verification: `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run pytest -q tests/test_agent_tools.py` covers a full quarantine/approved schema-alignment/verification/release cycle, a rerun whose defect persists, configured-role enforcement, direct high-risk bypass rejection, idempotency, audit entries, and strict payload schemas. CP-7 persists audit and orchestrator events across restarts. The measured safety probes below cover three specific rejection conditions; these do not establish policy accuracy across arbitrary requests.

## CP-7 persistence and API

`SQLiteStore` writes domain records, agent snapshots, action proposals, approvals, tool audits, state transitions, outcomes, artifacts, and simulated runs to the configured SQLite database. On startup, the service graph reloads the persisted run records, incidents, tool state, and agent state; an empty store is seeded from the configured deterministic generator. The API is a thin adapter over `ApplicationServices`, `AgentOrchestrator`, and the registered tool boundary. A restart integration test executes a quarantine/rerun incident, starts a new app over the same SQLite file, and verifies that the run, escalated incident, workflow state, and action timeline remain available. A second restart integration completes the high-risk approval, repair, and trust-release path after restoring an approval-pending state.

## CP-8 dashboard evidence and CP-9 operational evaluation

The Streamlit UI has five API-backed views: overview, DQF processing, incident investigation, actions/approvals, and evaluation. Genuine browser captures from the running local app are saved under `output/dashboard_screenshots/`; the combined SIH presentation includes DQF processing, incident investigation, and action/approval examples. Screenshots demonstrate the UI state and are not benchmark measurements.

Operational evaluation command: `UV_CACHE_DIR=/tmp/datagard-uv-cache uv run python -m datagard.operational_evaluation`.

| Track | Fixed cases | Result | Median / maximum time |
|---|---:|---|---:|
| Runbook retrieval | 7 canonical queries | hit@1 6/7; hit@3 6/7; MRR 0.857 | 0.241 / 0.395 ms per query |
| RCA cause ranking | 5 synthetic cases | top-1 4/5; top-3 5/5 | 0.102 / 0.148 ms per case |
| Policy rejection probes | 3 invalid/unauthorized requests | rejected as expected 3/3 | 0.055 / 0.097 ms per probe |

The sets are small, fixed, and hand-authored. They provide functional evidence for these cases only, not population estimates. Retrieval misses the safe-rerun query, consistent with lexical TF-IDF limits. The policy probes test only three specific unsafe states. No end-to-end service latency or MTTD is reported. Saved case-level results are `artifacts/evaluation/operations/retrieval_queries.csv`, `rca_cases.csv`, and `safety_probes.csv`; the summary is `operational_metrics.json` and records the measured environment and timings.
