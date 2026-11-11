"""CP-5 incident, evidence-grounded RCA, and local retrieval tests."""

from datagard.config import get_settings
from datagard.ingestion import BASE_SCHEMA, generate_synthetic_dataset
from datagard.incidents import IncidentService
from datagard.metadata import LineageGraph
from datagard.quality import evaluate_quality
from datagard.rca import investigate_run
from datagard.rag import RunbookRetriever


def test_incident_service_groups_evidence_and_deduplicates() -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    run = next(run for run in dataset.runs if run.output_rows < run.input_rows)
    findings = evaluate_quality(run, BASE_SCHEMA, settings.quality)
    service = IncidentService()

    first = service.record_detection(run, findings, is_anomaly=True, detector_version="test-model")
    repeated = service.record_detection(run, findings, is_anomaly=True, detector_version="test-model")

    assert len(first) == 1
    assert first[0].incident_family == "ROW_COUNT_DROP"
    assert repeated[0].incident_id == first[0].incident_id
    assert len(service.list_incidents()) == 1
    assert service.record_detection(run, findings, is_anomaly=False, detector_version="test-model") == ()


def test_rca_returns_supported_cause_families_without_truth_input() -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    lineage = LineageGraph()
    lineage.add_dependency("orders_daily", "orders_source")
    cases = {
        "row_count_drop": "UPSTREAM_VOLUME_DROP",
        "schema_drift": "SCHEMA_DRIFT",
        "null_surge": "SOURCE_NULL_SURGE",
        "duplicate_spike": "DUPLICATE_KEY_GENERATION",
        "distribution_shift": "SOURCE_OR_TRANSFORM_SHIFT",
    }
    for scenario, expected_cause in cases.items():
        run = next(run for run in dataset.runs if next(label for label in dataset.labels if label.run_id == run.run_id).scenario_id == scenario)
        findings = evaluate_quality(run, BASE_SCHEMA, settings.quality, {"amount": (100.0, 10.0)})
        hypotheses = investigate_run(run, BASE_SCHEMA, findings, lineage, dataset.runs, settings=settings.rca)
        assert hypotheses
        assert expected_cause in {hypothesis.cause_code for hypothesis in hypotheses}
        supported = next(hypothesis for hypothesis in hypotheses if hypothesis.cause_code == expected_cause)
        assert supported.supporting_evidence_ids
        assert "orders_source" in supported.upstream_nodes

    runtime_run = next(
        run for run in dataset.runs
        if run.duration_ms > 60_000 and run.status == "SUCCESS"
    )
    clean_history = tuple(
        run for run, label in zip(dataset.runs, dataset.labels, strict=True)
        if label.scenario_id == "clean" and run.run_id != runtime_run.run_id
    )
    runtime_hypotheses = investigate_run(
        runtime_run, BASE_SCHEMA, (), lineage, clean_history, settings=settings.rca
    )
    assert runtime_hypotheses[0].cause_code == "EXECUTION_RESOURCE_OR_PARTITION"

    missing_run = next(
        run for run in dataset.runs
        if any(not metric.telemetry_available for metric in run.field_metrics.values())
        and any(label.run_id == run.run_id and label.scenario_id == "missing_telemetry" for label in dataset.labels)
    )
    missing_findings = evaluate_quality(missing_run, BASE_SCHEMA, settings.quality)
    missing_hypotheses = investigate_run(missing_run, BASE_SCHEMA, missing_findings, lineage)
    assert missing_hypotheses[0].cause_code == "INCONCLUSIVE"


def test_rca_labels_visual_regions_as_evidence_not_cause() -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    run = dataset.runs[0]
    # DIPRegion is intentionally passed only as an optional evidence object in this test.
    from datagard.contracts import DIPRegion

    region = DIPRegion(
        method="DIP-B0", component_id=1, x=0, y=0, width=1, height=1,
        centroid_x=0.0, centroid_y=0.0, area=1, peak_intensity=255, density=1.0,
        run_ids=(run.run_id,), channel_ids=("amount.mean",),
    )
    hypotheses = investigate_run(run, BASE_SCHEMA, (), LineageGraph(), dip_regions=(region,))
    assert hypotheses[0].cause_code == "VISUAL_TELEMETRY_PATTERN"
    assert "not a causal diagnosis" in hypotheses[0].summary


def test_local_runbook_retrieval_returns_stable_sources_and_relevant_text() -> None:
    settings = get_settings()
    retriever = RunbookRetriever(settings.retrieval, settings.resolved_runbooks_dir)

    results = retriever.retrieve("schema drift changed type field downstream contract")

    assert retriever.chunk_count >= 7
    assert 0 < len(results) <= settings.retrieval.top_k
    assert results[0].document_id == "schema_drift"
    assert results[0].section_id.startswith("schema_drift#")
    assert "schema" in results[0].text.lower()
    assert RunbookRetriever(settings.retrieval, settings.resolved_runbooks_dir).retrieve(
        "schema drift changed type field downstream contract"
    ) == results
