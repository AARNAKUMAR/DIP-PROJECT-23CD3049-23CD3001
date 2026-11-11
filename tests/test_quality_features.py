"""CP-2 quality-rule ownership and canonical feature tests."""

from datagard.config import get_settings
from datagard.contracts import QualityFinding
from datagard.features import build_feature_vector
from datagard.ingestion import generate_synthetic_dataset
from datagard.quality import evaluate_quality


def _run_for_scenario(scenario_id: str):
    dataset = generate_synthetic_dataset(get_settings())
    run_id = next(label.run_id for label in dataset.labels if label.scenario_id == scenario_id)
    return next(run for run in dataset.runs if run.run_id == run_id)


def test_quality_engine_flags_required_defect_families() -> None:
    settings = get_settings()
    normal = _run_for_scenario("clean")
    findings = evaluate_quality(normal, normal.observed_schema, settings.quality)
    assert findings == ()

    expected_ids = {
        "row_count_drop": {"ROW_COUNT_DROP"},
        "schema_drift": {"SCHEMA_FIELD_ADDED", "SCHEMA_TYPE_CHANGED"},
        "null_surge": {"NULL_RATE_MAX"},
        "duplicate_spike": {"DUPLICATE_RATE_MAX"},
        "distribution_shift": {"DISTRIBUTION_SHIFT", "INVALID_RANGE"},
    }
    base_schema = _run_for_scenario("clean").observed_schema
    for scenario_id, expected_rules in expected_ids.items():
        run = _run_for_scenario(scenario_id)
        rule_ids = {finding.rule_id for finding in evaluate_quality(run, base_schema, settings.quality, {"amount": (100.0, 20.0)})}
        assert expected_rules <= rule_ids


def test_quality_findings_are_stable_and_missing_telemetry_is_explicit() -> None:
    settings = get_settings()
    run = _run_for_scenario("missing_telemetry")

    first = evaluate_quality(run, run.observed_schema, settings.quality)
    second = evaluate_quality(run, run.observed_schema, settings.quality)

    assert first == second
    assert any(finding.rule_id == "TELEMETRY_MISSING" for finding in first)


def test_feature_builder_obeys_canonical_names_and_order() -> None:
    settings = get_settings()
    run = _run_for_scenario("combined_incident")
    expected_schema = _run_for_scenario("clean").observed_schema
    findings = evaluate_quality(run, expected_schema, settings.quality, {"amount": (100.0, 20.0)})

    vector = build_feature_vector(run, findings, settings.features, expected_schema, {"amount": (100.0, 20.0)})

    assert vector.feature_names == settings.features.names
    assert len(vector.values) == len(settings.features.names)
    assert vector.values[settings.features.names.index("output_drop_ratio")] > 0
    assert vector.values[settings.features.names.index("quality_finding_count")] == len(findings)
