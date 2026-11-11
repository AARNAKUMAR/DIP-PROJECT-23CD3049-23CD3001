"""Leakage-aware detector evaluation, metrics, and evidence artifacts."""

import csv
import json
import logging
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable

import numpy as np
from numpy.typing import NDArray
import sklearn
from sklearn.metrics import average_precision_score

from datagard.config import Settings
from datagard.contracts import DetectionMetrics, FeatureVector, PipelineRun, QualityFinding, ScenarioTruth
from datagard.detection import IsolationForestDetector, rule_baseline_is_anomaly
from datagard.dip.encoder import BaselineProfile, encode_fingerprint, fit_channel_baselines
from datagard.dip.processor import process_fingerprint
from datagard.dip.region_features import current_row_region_features
from datagard.features import build_feature_vector
from datagard.ingestion import generate_synthetic_dataset, write_synthetic_dataset
from datagard.quality import evaluate_quality
from datagard.splits import GroupedDataSplit, split_by_incident_group

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionBenchmarkResult:
    """Paths to detector metrics, predictions, split, and model artifacts."""

    summary_path: Path
    metrics_path: Path
    predictions_path: Path
    confusion_matrices_path: Path
    scenario_metrics_path: Path
    model_paths: tuple[Path, ...]
    summary: dict[str, object]


def evaluate_detection(
    dataset,
    settings: Settings,
    output_dir: Path | None = None,
    model_dir: Path | None = None,
) -> DetectionBenchmarkResult:
    """Fit models on clean train groups, tune thresholds on validation, test once."""

    labels = {truth.run_id: truth for truth in dataset.labels}
    runs = tuple(sorted(dataset.runs, key=lambda run: (run.started_at, run.run_id)))
    split = split_by_incident_group(
        runs,
        labels,
        settings.evaluation.training_group_fraction,
        settings.evaluation.validation_group_fraction,
    )
    training_clean = tuple(
        run for run in split.training_runs if labels[run.run_id].scenario_id == "clean"
    )
    if len(training_clean) < 2:
        raise ValueError("The training partition must contain at least two clean runs")

    reference_schema = training_clean[0].observed_schema
    distribution_baselines = _fit_distribution_baselines(training_clean)
    baseline_profile = fit_channel_baselines(training_clean, settings.dip, reference_schema)

    training_dip = _region_features_for_partition(
        split.training_runs, settings, baseline_profile, reference_schema
    )
    validation_dip = _region_features_for_partition(
        split.validation_runs, settings, baseline_profile, reference_schema
    )
    test_dip = _region_features_for_partition(
        split.test_runs, settings, baseline_profile, reference_schema
    )
    train_base, train_augmented, train_findings = _build_feature_records(
        split.training_runs, settings, reference_schema, distribution_baselines, training_dip
    )
    validation_base, validation_augmented, validation_findings = _build_feature_records(
        split.validation_runs, settings, reference_schema, distribution_baselines, validation_dip
    )
    test_base, test_augmented, test_findings = _build_feature_records(
        split.test_runs, settings, reference_schema, distribution_baselines, test_dip
    )

    model_output_dir = model_dir or settings.resolved_model_dir
    evaluation_output_dir = output_dir or settings.resolved_evaluation_dir
    model_output_dir.mkdir(parents=True, exist_ok=True)
    evaluation_output_dir.mkdir(parents=True, exist_ok=True)
    prediction_rows: list[dict[str, object]] = []
    metrics: list[DetectionMetrics] = []
    validation_thresholds: dict[str, dict[str, float | int]] = {}
    model_paths: list[Path] = []

    test_truth = _truth_values(split.test_runs, labels)
    baseline_test = np.asarray(
        [
            rule_baseline_is_anomaly(test_findings[run.run_id], settings.detection.baseline_severities)
            for run in split.test_runs
        ],
        dtype=np.bool_,
    )
    rule_metric = _make_metrics(
        "rule_baseline",
        test_truth,
        baseline_test,
        None,
    )
    metrics.append(rule_metric)
    prediction_rows.extend(
        _prediction_records(
            "rule_baseline",
            split.test_runs,
            labels,
            baseline_test,
            None,
            None,
            test_findings,
        )
    )

    structured_model = _fit_and_evaluate_variant(
        "isolation_forest_structured",
        training_clean,
        train_base,
        split.validation_runs,
        validation_base,
        split.test_runs,
        test_base,
        train_findings,
        validation_findings,
        test_findings,
        labels,
        settings,
        model_output_dir / "isolation_forest_structured.joblib",
    )
    metrics.append(structured_model["metrics"])
    validation_thresholds["isolation_forest_structured"] = structured_model["validation_threshold"]
    model_paths.append(structured_model["model_path"])
    prediction_rows.extend(structured_model["predictions"])

    common_train_runs = tuple(run for run in training_clean if run.run_id in train_augmented)
    common_validation_runs = tuple(run for run in split.validation_runs if run.run_id in validation_augmented)
    common_test_runs = tuple(run for run in split.test_runs if run.run_id in test_augmented)
    if len(common_train_runs) < 2 or not common_validation_runs or not common_test_runs:
        raise ValueError("DIP ablation requires train, validation, and test runs with a full causal window")

    ablation_structured = _fit_and_evaluate_variant(
        "ablation_structured_only",
        common_train_runs,
        train_base,
        common_validation_runs,
        validation_base,
        common_test_runs,
        test_base,
        train_findings,
        validation_findings,
        test_findings,
        labels,
        settings,
        model_output_dir / "isolation_forest_ablation_structured.joblib",
    )
    ablation_augmented = _fit_and_evaluate_variant(
        "ablation_structured_plus_dip",
        common_train_runs,
        train_augmented,
        common_validation_runs,
        validation_augmented,
        common_test_runs,
        test_augmented,
        train_findings,
        validation_findings,
        test_findings,
        labels,
        settings,
        model_output_dir / "isolation_forest_ablation_structured_dip.joblib",
    )
    for result in (ablation_structured, ablation_augmented):
        metrics.append(result["metrics"])
        validation_thresholds[result["metrics"].detector_name] = result["validation_threshold"]
        model_paths.append(result["model_path"])
        prediction_rows.extend(result["predictions"])

    scenario_rows = _scenario_metrics(prediction_rows)
    split_metadata = _split_metadata(split, labels)
    summary: dict[str, object] = {
        "model_version": settings.detection.model_version,
        "feature_names": {
            "structured": settings.features.names,
            "structured_plus_dip": settings.features.names + settings.features.dip_region_names,
        },
        "model_parameters": settings.detection.model_dump(mode="json"),
        "split": split_metadata,
        "training_run_count": len(split.training_runs),
        "training_clean_run_count": len(training_clean),
        "validation_run_count": len(split.validation_runs),
        "test_run_count": len(split.test_runs),
        "test_positive_count": int(test_truth.sum()),
        "test_negative_count": int(len(test_truth) - test_truth.sum()),
        "ablation_run_counts": {
            "training_clean": len(common_train_runs),
            "validation": len(common_validation_runs),
            "test": len(common_test_runs),
        },
        "validation_thresholds": validation_thresholds,
        "metrics": [metric.model_dump(mode="json") for metric in metrics],
        "scenario_metrics": scenario_rows,
        "runtime_environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "metric_notes": {
            "average_precision": "scikit-learn average_precision_score; not trapezoidal PR-AUC",
            "anomaly_score": "negative decision_function; larger scores indicate greater anomaly; not a probability",
            "threshold_selection": "maximum validation F1; ties choose the higher (more conservative) score threshold",
        },
    }

    summary_path = evaluation_output_dir / "detection_metrics.json"
    metrics_path = evaluation_output_dir / "detection_metrics.csv"
    predictions_path = evaluation_output_dir / "detection_predictions.csv"
    confusion_path = evaluation_output_dir / "detection_confusion_matrices.csv"
    scenario_path = evaluation_output_dir / "detection_scenario_metrics.csv"
    split_path = evaluation_output_dir / "detection_split.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=list) + "\n", encoding="utf-8")
    split_path.write_text(json.dumps(split_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(metrics_path, (metric.model_dump(mode="json") for metric in metrics))
    _write_csv(predictions_path, prediction_rows)
    _write_csv(
        confusion_path,
        (
            {
                "detector_name": metric.detector_name,
                "sample_count": metric.sample_count,
                "true_positive": metric.true_positive,
                "false_positive": metric.false_positive,
                "false_negative": metric.false_negative,
                "true_negative": metric.true_negative,
            }
            for metric in metrics
        ),
    )
    _write_csv(scenario_path, scenario_rows)
    logger.info("detector benchmark completed", extra={"test_runs": len(split.test_runs)})
    return DetectionBenchmarkResult(
        summary_path,
        metrics_path,
        predictions_path,
        confusion_path,
        scenario_path,
        tuple(model_paths),
        summary,
    )


def select_f1_threshold(
    truth: NDArray[np.bool_], scores: NDArray[np.float64]
) -> tuple[float, float]:
    """Select the score threshold by validation F1 with conservative tie-break."""

    if truth.ndim != 1 or scores.ndim != 1 or len(truth) != len(scores) or len(truth) == 0:
        raise ValueError("Threshold selection needs non-empty aligned truth and score vectors")
    candidates = [float(value) for value in np.unique(scores)]
    candidates.append(float(np.nextafter(float(np.max(scores)), np.inf)))
    best_threshold = candidates[0]
    best_f1 = -1.0
    for threshold in candidates:
        predicted = scores >= threshold
        f1 = _make_metrics("validation", truth, predicted, None).f1
        if f1 > best_f1 or (f1 == best_f1 and threshold > best_threshold):
            best_f1 = f1
            best_threshold = threshold
    return best_threshold, best_f1


def main() -> None:
    """Generate the deterministic dataset and save detector evaluation evidence."""

    settings = Settings()
    dataset = generate_synthetic_dataset(settings)
    write_synthetic_dataset(dataset, settings.resolved_data_output_dir)
    result = evaluate_detection(dataset, settings)
    print(f"Detection metrics: {result.summary_path}")
    print(f"Predictions: {result.predictions_path}")


def _fit_and_evaluate_variant(
    detector_name: str,
    training_runs: tuple[PipelineRun, ...],
    training_vectors: dict[str, FeatureVector],
    validation_runs: tuple[PipelineRun, ...],
    validation_vectors: dict[str, FeatureVector],
    test_runs: tuple[PipelineRun, ...],
    test_vectors: dict[str, FeatureVector],
    training_findings: dict[str, tuple[QualityFinding, ...]],
    validation_findings: dict[str, tuple[QualityFinding, ...]],
    test_findings: dict[str, tuple[QualityFinding, ...]],
    labels: dict[str, ScenarioTruth],
    settings: Settings,
    model_path: Path,
) -> dict[str, object]:
    training_matrix, feature_names = _matrix(training_runs, training_vectors)
    validation_matrix, validation_names = _matrix(validation_runs, validation_vectors)
    test_matrix, test_names = _matrix(test_runs, test_vectors)
    if feature_names != validation_names or feature_names != test_names:
        raise ValueError("Feature names/order differ between train, validation, and test")

    detector = IsolationForestDetector(settings.detection)
    detector.fit(training_matrix, feature_names)
    validation_scores = detector.score(validation_matrix)
    validation_truth = _truth_values(validation_runs, labels)
    threshold, validation_f1 = select_f1_threshold(validation_truth, validation_scores)
    test_scores = detector.score(test_matrix)
    test_truth = _truth_values(test_runs, labels)
    test_predictions = test_scores >= threshold
    detection_metrics = _make_metrics(detector_name, test_truth, test_predictions, test_scores)
    detector.save(model_path)
    return {
        "metrics": detection_metrics,
        "validation_threshold": {
            "threshold": threshold,
            "validation_f1": validation_f1,
            "validation_sample_count": len(validation_runs),
            "validation_positive_count": int(validation_truth.sum()),
        },
        "model_path": model_path,
        "predictions": _prediction_records(
            detector_name,
            test_runs,
            labels,
            test_predictions,
            test_scores,
            threshold,
            test_findings,
        ),
    }


def _build_feature_records(
    runs: tuple[PipelineRun, ...],
    settings: Settings,
    reference_schema,
    distribution_baselines: dict[str, tuple[float, float]],
    dip_features: dict[str, dict[str, float]],
) -> tuple[
    dict[str, FeatureVector],
    dict[str, FeatureVector],
    dict[str, tuple[QualityFinding, ...]],
]:
    structured: dict[str, FeatureVector] = {}
    augmented: dict[str, FeatureVector] = {}
    findings_by_run: dict[str, tuple[QualityFinding, ...]] = {}
    for run in runs:
        findings = evaluate_quality(run, reference_schema, settings.quality, distribution_baselines)
        findings_by_run[run.run_id] = findings
        structured[run.run_id] = build_feature_vector(
            run,
            findings,
            settings.features,
            reference_schema,
            distribution_baselines,
        )
        if run.run_id in dip_features:
            augmented[run.run_id] = build_feature_vector(
                run,
                findings,
                settings.features,
                reference_schema,
                distribution_baselines,
                dip_features[run.run_id],
            )
    return structured, augmented, findings_by_run


def _region_features_for_partition(
    runs: tuple[PipelineRun, ...],
    settings: Settings,
    baseline: BaselineProfile,
    reference_schema,
) -> dict[str, dict[str, float]]:
    """Create causal current-run region features from partition-local history."""

    ordered_runs = tuple(sorted(runs, key=lambda run: (run.started_at, run.run_id)))
    window_size = settings.dip.window_size
    region_features: dict[str, dict[str, float]] = {}
    for end_index in range(window_size - 1, len(ordered_runs)):
        window = ordered_runs[end_index - window_size + 1 : end_index + 1]
        fingerprint = encode_fingerprint(window, settings.dip, baseline, reference_schema)
        processed = process_fingerprint(fingerprint, settings.dip)
        selected_mask = (
            processed.baseline.mask
            if settings.detection.ablation_dip_method == "DIP-B0"
            else processed.improved.mask
        )
        selected_result = (
            processed.baseline
            if settings.detection.ablation_dip_method == "DIP-B0"
            else processed.improved
        )
        region_features[ordered_runs[end_index].run_id] = current_row_region_features(
            selected_mask, fingerprint.validity_mask
        )
        if selected_result.method != settings.detection.ablation_dip_method:
            raise RuntimeError("Configured DIP method did not match the processor result")
    return region_features


def _fit_distribution_baselines(
    clean_runs: tuple[PipelineRun, ...],
) -> dict[str, tuple[float, float]]:
    """Estimate field mean/std baselines from clean training runs only."""

    field_values: dict[str, list[float]] = {}
    for run in clean_runs:
        for field_id, metrics in run.field_metrics.items():
            if metrics.mean is not None and metrics.telemetry_available:
                field_values.setdefault(field_id, []).append(metrics.mean)
    return {
        field_id: (mean(values), pstdev(values))
        for field_id, values in field_values.items()
        if len(values) > 1 and pstdev(values) > 0.0
    }


def _matrix(
    runs: tuple[PipelineRun, ...],
    vectors: dict[str, FeatureVector],
) -> tuple[NDArray[np.float64], tuple[str, ...]]:
    if not runs:
        raise ValueError("Cannot build a model matrix from an empty run set")
    rows = [vectors[run.run_id] for run in runs]
    names = rows[0].feature_names
    if any(row.feature_names != names for row in rows):
        raise ValueError("Feature vector order changed inside a data partition")
    return np.asarray([row.values for row in rows], dtype=np.float64), names


def _truth_values(
    runs: tuple[PipelineRun, ...], labels: dict[str, ScenarioTruth]
) -> NDArray[np.bool_]:
    return np.asarray([labels[run.run_id].is_incident for run in runs], dtype=np.bool_)


def _make_metrics(
    detector_name: str,
    truth: NDArray[np.bool_],
    predictions: NDArray[np.bool_],
    scores: NDArray[np.float64] | None,
) -> DetectionMetrics:
    if truth.shape != predictions.shape or truth.ndim != 1:
        raise ValueError("Truth and prediction arrays must be aligned one-dimensional vectors")
    if scores is not None and scores.shape != truth.shape:
        raise ValueError("Anomaly scores must align with truth and prediction arrays")
    true_positive = int(np.logical_and(truth, predictions).sum())
    false_positive = int(np.logical_and(~truth, predictions).sum())
    false_negative = int(np.logical_and(truth, ~predictions).sum())
    true_negative = int(np.logical_and(~truth, ~predictions).sum())
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    f1_denominator = 2 * true_positive + false_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = 2 * true_positive / f1_denominator if f1_denominator else 0.0
    average_precision = None
    if scores is not None and truth.any():
        average_precision = float(average_precision_score(truth, scores))
    return DetectionMetrics(
        detector_name=detector_name,
        sample_count=len(truth),
        positive_count=int(truth.sum()),
        negative_count=int(len(truth) - truth.sum()),
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        precision=precision,
        recall=recall,
        f1=f1,
        average_precision=average_precision,
    )


def _prediction_records(
    detector_name: str,
    runs: tuple[PipelineRun, ...],
    labels: dict[str, ScenarioTruth],
    predictions: NDArray[np.bool_],
    scores: NDArray[np.float64] | None,
    threshold: float | None,
    findings_by_run: dict[str, tuple[QualityFinding, ...]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, run in enumerate(runs):
        rows.append(
            {
                "detector_name": detector_name,
                "run_id": run.run_id,
                "scenario_id": labels[run.run_id].scenario_id,
                "incident_group_id": labels[run.run_id].incident_group_id,
                "truth_is_incident": labels[run.run_id].is_incident,
                "anomaly_score": float(scores[index]) if scores is not None else None,
                "threshold": threshold,
                "predicted_is_incident": bool(predictions[index]),
                "evidence_refs": ";".join(finding.finding_id for finding in findings_by_run[run.run_id]),
            }
        )
    return rows


def _scenario_metrics(prediction_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    detector_names = sorted({str(row["detector_name"]) for row in prediction_rows})
    for detector_name in detector_names:
        detector_rows = [row for row in prediction_rows if row["detector_name"] == detector_name]
        for scenario_id in sorted({str(row["scenario_id"]) for row in detector_rows}):
            selected = [row for row in detector_rows if row["scenario_id"] == scenario_id]
            truth = np.asarray([bool(row["truth_is_incident"]) for row in selected], dtype=np.bool_)
            predictions = np.asarray([bool(row["predicted_is_incident"]) for row in selected], dtype=np.bool_)
            metric = _make_metrics(detector_name, truth, predictions, None)
            results.append({"scenario_id": scenario_id, **metric.model_dump(mode="json")})
    return results


def _split_metadata(
    split: GroupedDataSplit,
    labels: dict[str, ScenarioTruth],
) -> dict[str, object]:
    return {
        "method": "chronological incident-group holdout",
        "training_group_ids": split.training_group_ids,
        "validation_group_ids": split.validation_group_ids,
        "test_group_ids": split.test_group_ids,
        "train_validation_group_overlap": sorted(
            set(split.training_group_ids) & set(split.validation_group_ids)
        ),
        "train_test_group_overlap": sorted(set(split.training_group_ids) & set(split.test_group_ids)),
        "validation_test_group_overlap": sorted(
            set(split.validation_group_ids) & set(split.test_group_ids)
        ),
        "training_run_ids": tuple(run.run_id for run in split.training_runs),
        "validation_run_ids": tuple(run.run_id for run in split.validation_runs),
        "test_run_ids": tuple(run.run_id for run in split.test_runs),
        "train_positive_count": sum(labels[run.run_id].is_incident for run in split.training_runs),
        "validation_positive_count": sum(labels[run.run_id].is_incident for run in split.validation_runs),
        "test_positive_count": sum(labels[run.run_id].is_incident for run in split.test_runs),
    }


def _write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    records = list(rows)
    fieldnames = list(records[0]) if records else []
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(records)


if __name__ == "__main__":
    main()
