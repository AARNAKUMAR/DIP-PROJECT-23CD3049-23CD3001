"""Canonical, stable construction of named model feature vectors."""

from collections.abc import Mapping

from datagard.config import FeatureSettings
from datagard.contracts import FeatureVector, PipelineRun, QualityFinding, SchemaField
from datagard.metadata import SchemaRegistry


def build_feature_vector(
    run: PipelineRun,
    findings: tuple[QualityFinding, ...],
    feature_settings: FeatureSettings,
    expected_schema: tuple[SchemaField, ...],
    distribution_baselines: Mapping[str, tuple[float, float]] | None = None,
    dip_region_features: Mapping[str, float] | None = None,
) -> FeatureVector:
    """Build one numeric vector using the configured canonical feature order."""

    null_rates = [metric.null_rate for metric in run.field_metrics.values() if metric.null_rate is not None]
    key_field_ids = {field.field_id for field in run.observed_schema if field.is_key}
    duplicate_rates = [
        (run.input_rows - metric.distinct_count) / run.input_rows
        for field_id, metric in run.field_metrics.items()
        if field_id in key_field_ids and metric.distinct_count is not None and run.input_rows > 0
    ]
    schema_diff = SchemaRegistry.diff(expected_schema, run.observed_schema)
    baselines = distribution_baselines or {}
    z_scores = [
        abs(metric.mean - baselines[field_id][0]) / baselines[field_id][1]
        for field_id, metric in run.field_metrics.items()
        if field_id in baselines and metric.mean is not None and baselines[field_id][1] > 0
    ]
    values_by_name = {
        "input_rows": float(run.input_rows),
        "output_drop_ratio": float(max(0, run.input_rows - run.output_rows) / run.input_rows) if run.input_rows else 0.0,
        "duration_ms": float(run.duration_ms),
        "mean_null_rate": sum(null_rates) / len(null_rates) if null_rates else 0.0,
        "max_null_rate": max(null_rates, default=0.0),
        "max_duplicate_rate": max(0.0, max(duplicate_rates, default=0.0)),
        "schema_change_count": float(len(schema_diff.added) + len(schema_diff.removed) + len(schema_diff.renamed) + len(schema_diff.type_changed)),
        "invalid_range_count": float(sum(finding.rule_id == "INVALID_RANGE" for finding in findings)),
        "distribution_z_score_max": max(z_scores, default=0.0),
        "missing_telemetry_count": float(sum(not metric.telemetry_available for metric in run.field_metrics.values())),
        "quality_finding_count": float(len(findings)),
    }
    feature_names = feature_settings.names
    if dip_region_features is not None:
        if set(dip_region_features) != set(feature_settings.dip_region_names):
            raise ValueError("DIP region features must match the configured feature names exactly")
        values_by_name.update(dip_region_features)
        feature_names += feature_settings.dip_region_names
    unsupported = set(feature_names) - values_by_name.keys()
    if unsupported:
        raise ValueError(f"Unsupported configured feature names: {', '.join(sorted(unsupported))}")
    if len(set(feature_names)) != len(feature_names):
        raise ValueError("Configured feature names must be unique")

    return FeatureVector(
        feature_names=feature_names,
        values=tuple(values_by_name[name] for name in feature_names),
    )
