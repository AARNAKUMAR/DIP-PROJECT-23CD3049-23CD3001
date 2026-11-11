"""CP-1 synthetic data, ingestion, and metadata acceptance tests."""

import json

import pytest

from datagard.config import Settings
from datagard.ingestion import (
    IngestionError,
    generate_synthetic_dataset,
    load_pipeline_runs,
    write_synthetic_dataset,
)
from datagard.metadata import LineageGraph, SchemaRegistry


def _small_settings() -> Settings:
    return Settings(runs_per_scenario=2)


def test_generator_is_deterministic_and_labels_cover_required_scenarios() -> None:
    first = generate_synthetic_dataset(_small_settings())
    second = generate_synthetic_dataset(_small_settings())

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert {label.scenario_id for label in first.labels} == {
        "clean", "row_count_drop", "schema_drift", "null_surge", "duplicate_spike",
        "distribution_shift", "runtime_spike", "combined_incident",
        "benign_seasonality", "missing_telemetry",
    }
    assert len(first.runs) == len(first.labels)
    assert not hasattr(first.runs[0], "is_incident")


def test_jsonl_round_trip_keeps_truth_in_a_separate_file(tmp_path) -> None:
    dataset = generate_synthetic_dataset(_small_settings())
    run_path, label_path = write_synthetic_dataset(dataset, tmp_path)

    loaded = load_pipeline_runs(run_path)
    assert len(loaded) == len(dataset.runs)
    assert "is_incident" not in json.loads(run_path.read_text().splitlines()[0])
    assert "is_incident" in json.loads(label_path.read_text().splitlines()[0])


def test_ingestion_rejects_malformed_record_with_line_number(tmp_path) -> None:
    source = tmp_path / "malformed.jsonl"
    source.write_text('{"run_id":"incomplete"}\n')

    with pytest.raises(IngestionError, match=r"malformed.jsonl:1"):
        load_pipeline_runs(source)


def test_schema_diff_and_lineage_are_centralized() -> None:
    dataset = generate_synthetic_dataset(_small_settings())
    normal_schema = dataset.runs[0].observed_schema
    changed_schema = next(run.observed_schema for run in dataset.runs if run.schema_version == "v2")
    diff = SchemaRegistry.diff(normal_schema, changed_schema)

    assert diff.added == ("discount_code",)
    assert diff.type_changed == (("customer_id", "integer", "string"),)

    graph = LineageGraph()
    graph.add_dependency("orders_daily", "customer_snapshot")
    assert graph.upstream_of("orders_daily") == ("customer_snapshot",)
    assert graph.downstream_of("customer_snapshot") == ("orders_daily",)
