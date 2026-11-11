"""Single owner of deterministic structured data-quality rules."""

import logging
from collections.abc import Mapping

from datagard.config import QualitySettings
from datagard.contracts import PipelineRun, QualityFinding, SchemaField
from datagard.metadata import SchemaDiff, SchemaRegistry

logger = logging.getLogger(__name__)


def evaluate_quality(
    run: PipelineRun,
    expected_schema: tuple[SchemaField, ...],
    settings: QualitySettings,
    distribution_baselines: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[QualityFinding, ...]:
    """Evaluate configured quality rules once for the supplied run."""

    findings: list[QualityFinding] = []
    baselines = distribution_baselines or {}

    for field_id, field_metrics in run.field_metrics.items():
        if not field_metrics.telemetry_available:
            findings.append(
                _finding(
                    run,
                    "TELEMETRY_MISSING",
                    field_id,
                    "LOW",
                    None,
                    None,
                    f"Telemetry for {field_id} is unavailable.",
                    {"field_id": field_id},
                )
            )
        if field_metrics.null_rate is not None and field_metrics.null_rate > settings.null_rate_max:
            findings.append(
                _finding(
                    run,
                    "NULL_RATE_MAX",
                    field_id,
                    "HIGH",
                    field_metrics.null_rate,
                    settings.null_rate_max,
                    f"Null rate for {field_id} exceeds the configured maximum.",
                    {"null_rate": field_metrics.null_rate, "threshold": settings.null_rate_max},
                )
            )

        schema_field = next((item for item in run.observed_schema if item.field_id == field_id), None)
        if schema_field is not None and schema_field.is_key and field_metrics.distinct_count is not None and run.input_rows:
            duplicate_count = max(0, run.input_rows - field_metrics.distinct_count)
            duplicate_rate = duplicate_count / run.input_rows
            if duplicate_rate > settings.duplicate_rate_max:
                findings.append(
                    _finding(
                        run,
                        "DUPLICATE_RATE_MAX",
                        field_id,
                        "HIGH",
                        duplicate_rate,
                        settings.duplicate_rate_max,
                        f"Duplicate rate for key {field_id} exceeds the configured maximum.",
                        {"duplicate_count": duplicate_count, "row_count": run.input_rows, "duplicate_rate": duplicate_rate},
                    )
                )

        configured_range = settings.field_ranges.get(field_id)
        if configured_range is not None:
            minimum, maximum = configured_range
            if (field_metrics.minimum is not None and field_metrics.minimum < minimum) or (
                field_metrics.maximum is not None and field_metrics.maximum > maximum
            ):
                findings.append(
                    _finding(
                        run,
                        "INVALID_RANGE",
                        field_id,
                        "MEDIUM",
                        f"{field_metrics.minimum}:{field_metrics.maximum}",
                        f"{minimum}:{maximum}",
                        f"Observed range for {field_id} is outside its configured bounds.",
                        {"minimum": field_metrics.minimum, "maximum": field_metrics.maximum},
                    )
                )

        baseline = baselines.get(field_id)
        if baseline is not None and field_metrics.mean is not None:
            baseline_mean, baseline_standard_deviation = baseline
            if baseline_standard_deviation > 0:
                z_score = abs(field_metrics.mean - baseline_mean) / baseline_standard_deviation
                if z_score > settings.distribution_z_score_max:
                    findings.append(
                        _finding(
                            run,
                            "DISTRIBUTION_SHIFT",
                            field_id,
                            "MEDIUM",
                            z_score,
                            settings.distribution_z_score_max,
                            f"Mean for {field_id} deviates from its configured history baseline.",
                            {"mean": field_metrics.mean, "baseline_mean": baseline_mean, "z_score": z_score},
                        )
                    )

    if run.input_rows > 0:
        row_drop_ratio = max(0, run.input_rows - run.output_rows) / run.input_rows
        if row_drop_ratio > settings.row_count_drop_max:
            findings.append(
                _finding(
                    run,
                    "ROW_COUNT_DROP",
                    None,
                    "HIGH",
                    row_drop_ratio,
                    settings.row_count_drop_max,
                    "Output row count dropped beyond the configured maximum.",
                    {"input_rows": run.input_rows, "output_rows": run.output_rows, "drop_ratio": row_drop_ratio},
                )
            )

    if run.status == "FAILED":
        findings.append(
            _finding(run, "PIPELINE_FAILED", None, "HIGH", run.status, "SUCCESS", "Pipeline run failed.", {"status": run.status})
        )

    schema_diff = SchemaRegistry.diff(expected_schema, run.observed_schema)
    findings.extend(_schema_findings(run, schema_diff))
    logger.info("quality checks completed", extra={"run_id": run.run_id, "finding_count": len(findings)})
    return tuple(findings)


def _schema_findings(run: PipelineRun, diff: SchemaDiff) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for field_id in diff.added:
        findings.append(_finding(run, "SCHEMA_FIELD_ADDED", field_id, "MEDIUM", field_id, None, f"Field {field_id} was added.", {"field_id": field_id}))
    for field_id in diff.removed:
        findings.append(_finding(run, "SCHEMA_FIELD_REMOVED", field_id, "HIGH", field_id, None, f"Field {field_id} was removed.", {"field_id": field_id}))
    for old_name, new_name in diff.renamed:
        findings.append(_finding(run, "SCHEMA_FIELD_RENAMED", old_name, "HIGH", new_name, old_name, f"Field {old_name} was renamed to {new_name}.", {"old_name": old_name, "new_name": new_name}))
    for field_id, old_type, new_type in diff.type_changed:
        findings.append(_finding(run, "SCHEMA_TYPE_CHANGED", field_id, "HIGH", new_type, old_type, f"Type for {field_id} changed.", {"old_type": old_type, "new_type": new_type}))
    return findings


def _finding(
    run: PipelineRun,
    rule_id: str,
    field_id: str | None,
    severity: str,
    observed: float | int | str | None,
    expected: float | int | str | None,
    message: str,
    evidence: dict[str, object],
) -> QualityFinding:
    """Build a stable finding identifier from its run and rule location."""

    location = field_id or "run"
    return QualityFinding(
        finding_id=f"{run.run_id}:{rule_id}:{location}",
        run_id=run.run_id,
        rule_id=rule_id,
        field_id=field_id,
        severity=severity,  # validated by the canonical contract
        observed=observed,
        expected_or_baseline=expected,
        message=message,
        evidence=evidence,
        created_at=run.started_at,
    )
