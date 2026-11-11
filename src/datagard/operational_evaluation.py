"""Reproducible runbook retrieval and RCA evaluation on fixed synthetic cases."""

import csv
import json
import logging
import statistics
import time
from pathlib import Path

from datagard.config import get_settings
from datagard.contracts import ApprovalInput, IncidentActionInput, ReleaseBatchInput, RepairInput, ToolRequest
from datagard.ingestion import BASE_SCHEMA, generate_synthetic_dataset
from datagard.incidents import IncidentService
from datagard.metadata import LineageGraph
from datagard.quality import evaluate_quality
from datagard.rag import RunbookRetriever
from datagard.rca import investigate_run
from datagard.tools import ToolRegistry

logger = logging.getLogger(__name__)

RETRIEVAL_CASES = (
    ("schema_drift", "new field changed type schema compatibility producer consumer"),
    ("row_count_drop", "output rows sharply lower than input upstream source volume"),
    ("null_surge", "null values increased suddenly in source field"),
    ("duplicate_spike", "duplicate primary keys increased during key generation"),
    ("distribution_shift", "field distribution shifted from historical baseline"),
    ("safe_rerun", "retry failed pipeline safely without duplicate downstream writes"),
    ("escalation", "request human review when incident cannot be safely resolved"),
)
RCA_CASES = (
    ("row_count_drop", "UPSTREAM_VOLUME_DROP"),
    ("schema_drift", "SCHEMA_DRIFT"),
    ("null_surge", "SOURCE_NULL_SURGE"),
    ("duplicate_spike", "DUPLICATE_KEY_GENERATION"),
    ("distribution_shift", "SOURCE_OR_TRANSFORM_SHIFT"),
)


def main() -> None:
    settings = get_settings()
    output_dir = settings.evaluation.output_dir.parent / "operations"
    output_dir.mkdir(parents=True, exist_ok=True)
    retriever = RunbookRetriever(settings.retrieval, settings.resolved_runbooks_dir)
    retrieval_rows = []
    for expected_doc, query in RETRIEVAL_CASES:
        start = time.perf_counter_ns()
        results = retriever.retrieve(query)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        ranked_docs = [item.document_id for item in results]
        rank = ranked_docs.index(expected_doc) + 1 if expected_doc in ranked_docs else None
        retrieval_rows.append({
            "query_id": expected_doc,
            "expected_document": expected_doc,
            "top1_document": ranked_docs[0] if ranked_docs else "",
            "rank_of_expected": rank or "",
            "hit_at_1": int(rank == 1),
            "hit_at_3": int(rank is not None and rank <= 3),
            "reciprocal_rank": 1 / rank if rank else 0.0,
            "latency_ms": elapsed_ms,
            "top_refs": "|".join(item.section_id for item in results),
        })

    dataset = generate_synthetic_dataset(settings)
    lineage = LineageGraph()
    lineage.add_dependency("orders_daily", "orders_source")
    rca_rows = []
    for scenario, expected_cause in RCA_CASES:
        run = next(run for run, truth in zip(dataset.runs, dataset.labels, strict=True) if truth.scenario_id == scenario)
        findings = evaluate_quality(run, BASE_SCHEMA, settings.quality, {"amount": (100.0, 10.0)})
        start = time.perf_counter_ns()
        hypotheses = investigate_run(
            run, BASE_SCHEMA, findings, lineage, dataset.runs, settings=settings.rca
        )
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        causes = [hypothesis.cause_code for hypothesis in hypotheses]
        rca_rows.append({
            "scenario_id": scenario,
            "expected_top_cause": expected_cause,
            "predicted_top_cause": causes[0] if causes else "",
            "correct_top1": int(bool(causes) and causes[0] == expected_cause),
            "correct_in_top3": int(expected_cause in causes[:3]),
            "rank_of_expected": causes.index(expected_cause) + 1 if expected_cause in causes else "",
            "latency_ms": elapsed_ms,
            "evidence_count": len(findings),
        })

    schema_run = next(run for run, truth in zip(dataset.runs, dataset.labels, strict=True) if truth.scenario_id == "schema_drift")
    schema_findings = evaluate_quality(schema_run, BASE_SCHEMA, settings.quality)
    incident_service = IncidentService()
    incident = incident_service.record_detection(
        schema_run, schema_findings, is_anomaly=True, detector_version="operational-eval"
    )[0]
    registry = ToolRegistry(tuple(dataset.runs), incident_service, retriever, settings)
    quarantine = registry.execute(ToolRequest(
        tool_name="quarantine_batch",
        payload=IncidentActionInput(incident_id=incident.incident_id, idempotency_key="safety-setup"),
    ), "safety-evaluation")
    if quarantine.status != "SUCCEEDED":
        raise RuntimeError("Safety evaluation setup could not quarantine the test incident")
    probes = (
        ("unapproved_repair", ToolRequest(
            tool_name="simulate_repair",
            payload=RepairInput(incident_id=incident.incident_id, idempotency_key="safety-repair", approval_id="missing", action_id="unapproved", repair_kind="align_schema"),
        )),
        ("wrong_role_approval", ToolRequest(
            tool_name="record_approval",
            payload=ApprovalInput(action_id="wrong-role", decision="APPROVED", approver_role="viewer", reason="Probe unauthorized role"),
        )),
        ("release_without_verification", ToolRequest(
            tool_name="release_batch",
            payload=ReleaseBatchInput(incident_id=incident.incident_id, idempotency_key="safety-release", verification_run_id="unverified-run"),
        )),
    )
    safety_rows = []
    for probe_id, request in probes:
        start = time.perf_counter_ns()
        result = registry.execute(request, "safety-evaluation")
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        safety_rows.append({
            "probe_id": probe_id,
            "tool_name": request.tool_name,
            "result_status": result.status,
            "blocked_as_expected": int(result.status == "REJECTED"),
            "reason": result.data.get("reason", ""),
            "latency_ms": elapsed_ms,
        })
    if any(not row["blocked_as_expected"] for row in safety_rows):
        raise RuntimeError("A guarded action probe was not rejected")

    _write_csv(output_dir / "retrieval_queries.csv", retrieval_rows)
    _write_csv(output_dir / "rca_cases.csv", rca_rows)
    _write_csv(output_dir / "safety_probes.csv", safety_rows)
    retrieval_latencies = [row["latency_ms"] for row in retrieval_rows]
    rca_latencies = [row["latency_ms"] for row in rca_rows]
    safety_latencies = [row["latency_ms"] for row in safety_rows]
    summary = {
        "protocol": "Fixed canonical intent queries and one deterministic generated run per RCA family; evaluation labels are used only to select and score cases.",
        "retrieval": {
            "query_count": len(retrieval_rows),
            "relevant_document_count": sum(row["hit_at_3"] for row in retrieval_rows),
            "hit_at_1": sum(row["hit_at_1"] for row in retrieval_rows) / len(retrieval_rows),
            "hit_at_3": sum(row["hit_at_3"] for row in retrieval_rows) / len(retrieval_rows),
            "mrr": statistics.mean(row["reciprocal_rank"] for row in retrieval_rows),
            "median_latency_ms": statistics.median(retrieval_latencies),
            "max_latency_ms": max(retrieval_latencies),
        },
        "rca": {
            "case_count": len(rca_rows),
            "correct_top1": sum(row["correct_top1"] for row in rca_rows),
            "top1_accuracy": sum(row["correct_top1"] for row in rca_rows) / len(rca_rows),
            "correct_in_top3": sum(row["correct_in_top3"] for row in rca_rows),
            "top3_accuracy": sum(row["correct_in_top3"] for row in rca_rows) / len(rca_rows),
            "median_latency_ms": statistics.median(rca_latencies),
            "max_latency_ms": max(rca_latencies),
        },
        "policy_safety": {
            "probe_count": len(safety_rows),
            "blocked_as_expected": sum(row["blocked_as_expected"] for row in safety_rows),
            "rejection_rate": sum(row["blocked_as_expected"] for row in safety_rows) / len(safety_rows),
            "median_latency_ms": statistics.median(safety_latencies),
            "max_latency_ms": max(safety_latencies),
        },
    }
    (output_dir / "operational_metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    logger.info("operational evaluation saved", extra={"output_dir": str(output_dir)})
    print(json.dumps(summary, indent=2))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
