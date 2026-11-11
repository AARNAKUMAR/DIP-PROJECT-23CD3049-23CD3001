"""Synthetic telemetry generation and strict JSONL ingestion."""

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from datagard.config import Settings, get_settings
from datagard.contracts import (
    FieldMetrics,
    PipelineRun,
    ScenarioTruth,
    SchemaField,
    SyntheticDataset,
)

logger = logging.getLogger(__name__)

SCENARIO_LABELS: tuple[tuple[str, bool], ...] = (
    ("clean", False),
    ("row_count_drop", True),
    ("schema_drift", True),
    ("null_surge", True),
    ("duplicate_spike", True),
    ("distribution_shift", True),
    ("runtime_spike", True),
    ("combined_incident", True),
    ("benign_seasonality", False),
    ("missing_telemetry", False),
)

BASE_SCHEMA: tuple[SchemaField, ...] = (
    SchemaField(field_id="order_id", name="order_id", data_type="integer", nullable=False, is_key=True),
    SchemaField(field_id="customer_id", name="customer_id", data_type="integer", nullable=True, is_key=False),
    SchemaField(field_id="amount", name="amount", data_type="float", nullable=False, is_key=False),
)


class IngestionError(ValueError):
    """Raised when a source record cannot be normalized safely."""


def generate_synthetic_dataset(settings: Settings) -> SyntheticDataset:
    """Generate deterministic scenarios with labels outside run features."""

    rng = random.Random(settings.synthetic_seed)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runs: list[PipelineRun] = []
    labels: list[ScenarioTruth] = []
    ordinal = 0
    episodes = [
        (scenario_id, is_incident, episode_index)
        for scenario_id, is_incident in SCENARIO_LABELS
        for episode_index in range(settings.runs_per_scenario)
    ]
    rng.shuffle(episodes)

    for scenario_id, is_incident, episode_index in episodes:
        incident_group_id = f"{scenario_id}-{episode_index:03d}"
        for episode_run_index in range(settings.scenario_persistence_runs):
            sample_index = episode_index * settings.scenario_persistence_runs + episode_run_index
            run_id = f"run-{ordinal:05d}"
            started_at = base_time + timedelta(minutes=ordinal * 5)
            metrics = _scenario_metrics(scenario_id, sample_index, rng)
            observed_schema = _schema_for_scenario(scenario_id)
            schema_version = "v2" if scenario_id == "schema_drift" else "v1"
            input_rows = 1000 + rng.randint(-15, 15)
            output_rows = input_rows
            duration_ms = 20_000 + rng.randint(-1_500, 1_500)
            if scenario_id != "duplicate_spike":
                metrics["order_id"] = metrics["order_id"].model_copy(
                    update={"distinct_count": input_rows}
                )

            if scenario_id == "row_count_drop":
                output_rows = input_rows // 3
            elif scenario_id == "runtime_spike":
                duration_ms *= 5
            elif scenario_id == "combined_incident":
                output_rows = input_rows // 2
                metrics["customer_id"] = metrics["customer_id"].model_copy(update={"null_rate": 0.35})
                metrics["amount"] = metrics["amount"].model_copy(update={"mean": 520.0})
            elif scenario_id == "benign_seasonality":
                metrics["amount"] = metrics["amount"].model_copy(update={"mean": 145.0})

            completed_at = started_at + timedelta(milliseconds=duration_ms)
            run = PipelineRun(
                run_id=run_id,
                pipeline_id="orders_daily",
                started_at=started_at,
                completed_at=completed_at,
                status="FAILED" if scenario_id == "runtime_spike" and sample_index % 4 == 0 else "SUCCESS",
                input_rows=input_rows,
                output_rows=output_rows,
                duration_ms=duration_ms,
                schema_version=schema_version,
                source_id="warehouse.orders_raw",
                target_id="warehouse.orders_curated",
                field_metrics=metrics,
                observed_schema=observed_schema,
            )
            runs.append(run)
            labels.append(
                ScenarioTruth(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    incident_group_id=incident_group_id,
                    is_incident=is_incident,
                    incident_start_at=started_at if is_incident else None,
                )
            )
            ordinal += 1

    logger.info("generated synthetic dataset", extra={"run_count": len(runs), "seed": settings.synthetic_seed})
    return SyntheticDataset(runs=tuple(runs), labels=tuple(labels))


def write_synthetic_dataset(dataset: SyntheticDataset, output_dir: Path) -> tuple[Path, Path]:
    """Persist feature input and ground truth in separate JSONL files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    run_path = output_dir / "pipeline_runs.jsonl"
    label_path = output_dir / "scenario_truth.jsonl"
    _write_jsonl(run_path, (run.model_dump(mode="json") for run in dataset.runs))
    _write_jsonl(label_path, (label.model_dump(mode="json") for label in dataset.labels))
    return run_path, label_path


def main() -> None:
    """Generate the configured dataset into the local artifact directory."""

    settings = get_settings()
    run_path, label_path = write_synthetic_dataset(
        generate_synthetic_dataset(settings), settings.resolved_data_output_dir
    )
    logger.info("wrote synthetic data", extra={"runs_path": str(run_path), "labels_path": str(label_path)})
    print(f"Runs: {run_path}\nTruth labels: {label_path}")


def load_pipeline_runs(source_path: Path) -> tuple[PipelineRun, ...]:
    """Validate each JSONL record, reporting its source line on failure."""

    records: list[PipelineRun] = []
    with source_path.open("r", encoding="utf-8") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            if not line.strip():
                continue
            try:
                records.append(PipelineRun.model_validate_json(line))
            except ValidationError as exc:
                raise IngestionError(f"Invalid pipeline run at {source_path}:{line_number}: {exc}") from exc
    return tuple(records)


def _scenario_metrics(
    scenario_id: str, sample_index: int, rng: random.Random
) -> dict[str, FieldMetrics]:
    null_rate = 0.01 + rng.random() * 0.01
    amount_mean = 100.0 + rng.uniform(-5.0, 5.0)
    amount_std = 20.0 + rng.uniform(-2.0, 2.0)
    order_count = 1000 + rng.randint(-20, 20)
    customer_null_rate = null_rate

    if scenario_id == "null_surge":
        customer_null_rate = 0.25 + sample_index * 0.002
    if scenario_id == "duplicate_spike":
        order_count = 700 + sample_index
    if scenario_id == "distribution_shift":
        amount_mean = 420.0 + sample_index
        amount_std = 85.0
    if scenario_id == "missing_telemetry":
        customer_null_rate = None
        amount_mean = None

    return {
        "order_id": FieldMetrics(null_rate=0.0, distinct_count=order_count),
        "customer_id": FieldMetrics(null_rate=customer_null_rate, distinct_count=900),
        "amount": FieldMetrics(
            null_rate=null_rate,
            distinct_count=700,
            mean=amount_mean,
            standard_deviation=amount_std,
            minimum=0.0,
            maximum=250.0 if scenario_id != "distribution_shift" else 1200.0,
            telemetry_available=scenario_id != "missing_telemetry" or sample_index % 2 != 0,
        ),
    }


def _schema_for_scenario(scenario_id: str) -> tuple[SchemaField, ...]:
    if scenario_id != "schema_drift":
        return BASE_SCHEMA
    return (
        BASE_SCHEMA[0],
        BASE_SCHEMA[1].model_copy(update={"data_type": "string"}),
        *BASE_SCHEMA[2:],
        SchemaField(field_id="discount_code", name="discount_code", data_type="string", nullable=True, is_key=False),
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as destination:
        for row in rows:
            destination.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
