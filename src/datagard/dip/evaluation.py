"""Held-out synthetic-mask evaluation and saved DQF artifacts."""

import csv
import json
import logging
import platform
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Iterable

import numpy as np
import cv2
from numpy.typing import NDArray

from datagard.config import DIPSettings, Settings
from datagard.contracts import (
    DIPArtifactManifest,
    DIPRegion,
    PipelineRun,
    RegionSegmentationMetrics,
    ScenarioTruth,
    SchemaField,
    SegmentationMetrics,
    SyntheticDataset,
)
from datagard.dip.encoder import Fingerprint, encode_fingerprint, fit_channel_baselines
from datagard.dip.processor import (
    DIPProcessingResult,
    label_mask_components,
    process_fingerprint,
    save_color,
    save_grayscale,
)
from datagard.ingestion import generate_synthetic_dataset, write_synthetic_dataset
from datagard.splits import split_by_incident_group

logger = logging.getLogger(__name__)

GROUND_TRUTH_CHANNELS: dict[str, tuple[str, ...]] = {
    "clean": (),
    "row_count_drop": ("output_rows",),
    "schema_drift": ("schema.change_count",),
    "null_surge": ("customer_id.null_rate",),
    "duplicate_spike": ("order_id.distinct_count",),
    "distribution_shift": ("amount.mean", "amount.maximum"),
    "runtime_spike": ("duration_ms",),
    "combined_incident": ("output_rows", "customer_id.null_rate", "amount.mean"),
    "benign_seasonality": (),
    "missing_telemetry": (),
}


@dataclass(frozen=True)
class DIPBenchmarkResult:
    """Paths and measured segmentation summaries from one benchmark run."""

    summary_path: Path
    aggregate_metrics_path: Path
    region_metrics_path: Path
    scenario_metrics_path: Path
    manifest_paths: tuple[Path, ...]
    summary: dict[str, object]


def ground_truth_mask(
    fingerprint: Fingerprint,
    truth_by_run_id: dict[str, ScenarioTruth],
) -> NDArray[np.uint8]:
    """Map injected anomaly labels to independently specified expected pixels."""

    mask = np.zeros(fingerprint.pixels.shape, dtype=np.uint8)
    column_index = {channel_id: index for index, channel_id in enumerate(fingerprint.channel_ids)}
    for row_index, run_id in enumerate(fingerprint.run_ids):
        truth = truth_by_run_id[run_id]
        for channel_id in GROUND_TRUTH_CHANNELS[truth.scenario_id]:
            index = column_index.get(channel_id)
            if index is not None and fingerprint.validity_mask[row_index, index]:
                mask[row_index, index] = 255
    return mask


def evaluate_dip(
    dataset: SyntheticDataset,
    settings: Settings,
    artifact_dir: Path | None = None,
    evaluation_dir: Path | None = None,
) -> DIPBenchmarkResult:
    """Fit on training normal runs, process held-out incident groups, and save evidence."""

    dip_settings = settings.dip
    output_artifacts = artifact_dir or settings.resolved_dip_artifact_dir
    output_evaluation = evaluation_dir or settings.resolved_dip_evaluation_dir
    output_artifacts.mkdir(parents=True, exist_ok=True)
    output_evaluation.mkdir(parents=True, exist_ok=True)

    runs = tuple(sorted(dataset.runs, key=lambda run: (run.started_at, run.run_id)))
    labels = {truth.run_id: truth for truth in dataset.labels}
    data_split = split_by_incident_group(
        runs, labels, dip_settings.training_group_fraction
    )
    training_runs = data_split.training_runs
    evaluation_runs = data_split.test_runs
    split_metadata = {
        "method": "chronological incident-group holdout",
        "training_group_fraction": dip_settings.training_group_fraction,
        "training_group_ids": data_split.training_group_ids,
        "evaluation_group_ids": data_split.test_group_ids,
    }
    normal_training_runs = tuple(
        run for run in training_runs if labels[run.run_id].scenario_id == "clean"
    )
    if len(normal_training_runs) < 2:
        raise ValueError("Grouped training split must contain at least two clean runs for baseline fitting")
    reference_schema = _reference_schema(normal_training_runs)
    baseline = fit_channel_baselines(normal_training_runs, dip_settings, reference_schema)

    windows = _evaluation_windows(evaluation_runs, dip_settings)
    if not windows:
        raise ValueError("Held-out split did not contain a complete DQF window")

    aggregate_counts = {"DIP-B0": [0, 0, 0, 0], "DIP-P1": [0, 0, 0, 0]}
    aggregate_region_counts = {"DIP-B0": [0, 0, 0, 0, 0, 0.0], "DIP-P1": [0, 0, 0, 0, 0, 0.0]}
    scenario_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    runtimes: dict[str, list[float]] = {"DIP-B0": [], "DIP-P1": []}
    window_rows: list[dict[str, object]] = []
    region_window_rows: list[dict[str, object]] = []
    manifest_paths: list[Path] = []
    evaluated_run_ids: set[str] = set()

    for window_index, window_runs in enumerate(windows):
        fingerprint = encode_fingerprint(window_runs, dip_settings, baseline, reference_schema)
        processed = process_fingerprint(fingerprint, dip_settings)
        truth_mask = ground_truth_mask(fingerprint, labels)
        truth_components = label_mask_components(
            truth_mask, fingerprint.validity_mask, dip_settings.connected_components_connectivity
        )
        manifest_path = _save_window_artifacts(
            window_index,
            fingerprint,
            processed,
            truth_mask,
            dip_settings,
            baseline.version,
            output_artifacts,
        )
        manifest_paths.append(manifest_path)
        evaluated_run_ids.update(fingerprint.run_ids)

        for method, predicted_mask, runtime_ms in _method_outputs(processed):
            valid = fingerprint.validity_mask
            counts = _confusion_counts(predicted_mask, truth_mask, valid)
            _add_counts(aggregate_counts[method], counts)
            predicted_components = (
                processed.baseline.component_labels
                if method == "DIP-B0"
                else processed.improved.component_labels
            )
            region_counts = _region_confusion_counts(
                predicted_components,
                truth_components,
                dip_settings.region_match_iou_min,
            )
            _add_region_counts(aggregate_region_counts[method], region_counts)
            runtimes[method].append(runtime_ms)
            window_metrics = _metrics(method, counts).model_dump(mode="json")
            window_rows.append(
                {
                    "window_index": window_index,
                    "scenario_ids": ",".join(sorted({labels[run_id].scenario_id for run_id in fingerprint.run_ids})),
                    **window_metrics,
                }
            )
            region_window_rows.append(
                {
                    "window_index": window_index,
                    "method": method,
                    **_region_count_mapping(region_counts),
                }
            )
            for row_index, run_id in enumerate(fingerprint.run_ids):
                scenario_id = labels[run_id].scenario_id
                row_counts = _confusion_counts(
                    predicted_mask[row_index : row_index + 1],
                    truth_mask[row_index : row_index + 1],
                    valid[row_index : row_index + 1],
                )
                _add_counts(scenario_counts[(scenario_id, method)], row_counts)

        logger.info(
            "DIP window processed",
            extra={"window_index": window_index, "run_count": len(fingerprint.run_ids)},
        )

    aggregate_metrics = {
        method: _metrics(method, tuple(counts))
        for method, counts in aggregate_counts.items()
    }
    aggregate_region_metrics = {
        method: _region_metrics(method, tuple(counts), dip_settings.region_match_iou_min)
        for method, counts in aggregate_region_counts.items()
    }
    scenario_metrics = [
        {
            "scenario_id": scenario_id,
            **_metrics(method, tuple(counts)).model_dump(mode="json"),
        }
        for (scenario_id, method), counts in sorted(scenario_counts.items())
    ]
    summary: dict[str, object] = {
        "encoder_version": dip_settings.encoder_version,
        "baseline_version": dip_settings.baseline_version,
        "seed": settings.synthetic_seed,
        "runtime_environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
        "window_size": dip_settings.window_size,
        "window_stride": dip_settings.window_stride,
        "threshold_method": dip_settings.threshold_method,
        "morphology_operation": dip_settings.morphology_operation,
        "median_filter_enabled": dip_settings.median_filter_enabled,
        "split": split_metadata,
        "training_run_count": len(training_runs),
        "training_clean_run_count": len(normal_training_runs),
        "held_out_run_count": len(evaluation_runs),
        "evaluated_unique_run_count": len(evaluated_run_ids),
        "evaluated_window_count": len(windows),
        "window_coverage_fraction": len(evaluated_run_ids) / len(evaluation_runs),
        "valid_pixel_count": sum(counts[0] + counts[1] + counts[2] + counts[3] for counts in aggregate_counts.values()) // 2,
        "valid_pixel_count_per_method": {
            method: metric.valid_pixel_count for method, metric in aggregate_metrics.items()
        },
        "median_processing_ms_per_fingerprint": {
            method: median(durations) for method, durations in runtimes.items()
        },
        "aggregate_metrics": {
            method: metric.model_dump(mode="json")
            for method, metric in aggregate_metrics.items()
        },
        "aggregate_region_metrics": {
            method: metric.model_dump(mode="json")
            for method, metric in aggregate_region_metrics.items()
        },
        "scenario_metrics": scenario_metrics,
    }
    summary_path = output_evaluation / "dip_metrics.json"
    aggregate_path = output_evaluation / "dip_metrics.csv"
    scenario_path = output_evaluation / "dip_scenario_metrics.csv"
    window_path = output_evaluation / "dip_window_metrics.csv"
    region_metrics_path = output_evaluation / "dip_region_metrics.csv"
    region_window_path = output_evaluation / "dip_region_window_metrics.csv"
    split_path = output_evaluation / "dip_split.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    split_path.write_text(json.dumps(split_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_metrics_csv(aggregate_path, (metric.model_dump(mode="json") for metric in aggregate_metrics.values()))
    _write_metrics_csv(scenario_path, scenario_metrics)
    _write_metrics_csv(window_path, window_rows)
    _write_metrics_csv(
        region_metrics_path,
        (metric.model_dump(mode="json") for metric in aggregate_region_metrics.values()),
    )
    _write_metrics_csv(region_window_path, region_window_rows)
    return DIPBenchmarkResult(
        summary_path,
        aggregate_path,
        region_metrics_path,
        scenario_path,
        tuple(manifest_paths),
        summary,
    )


def _evaluation_windows(
    runs: tuple[PipelineRun, ...], settings: DIPSettings
) -> tuple[tuple[PipelineRun, ...], ...]:
    return tuple(
        runs[start : start + settings.window_size]
        for start in range(0, len(runs) - settings.window_size + 1, settings.window_stride)
    )


def _reference_schema(runs: tuple[PipelineRun, ...]) -> tuple[SchemaField, ...]:
    schema_versions = {run.schema_version for run in runs}
    if len(schema_versions) != 1:
        raise ValueError("Baseline training runs contain more than one schema version")
    return runs[0].observed_schema


def _save_window_artifacts(
    window_index: int,
    fingerprint: Fingerprint,
    processed: DIPProcessingResult,
    truth_mask: NDArray[np.uint8],
    settings: DIPSettings,
    baseline_version: str,
    artifact_root: Path,
) -> Path:
    window_name = f"window_{window_index:03d}"
    window_dir = artifact_root / window_name
    window_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "raw": window_dir / "fingerprint.png",
        "validity": window_dir / "validity_mask.png",
        "truth": window_dir / "ground_truth_mask.png",
        "filtered": window_dir / "improved_filtered.png",
        "adaptive": window_dir / "improved_adaptive_mask.png",
        "baseline": window_dir / "baseline_mask.png",
        "improved": window_dir / "improved_mask.png",
        "baseline_overlay": window_dir / "baseline_overlay.png",
        "improved_overlay": window_dir / "improved_overlay.png",
    }
    save_grayscale(paths["raw"], fingerprint.pixels)
    save_grayscale(paths["validity"], fingerprint.validity_mask.astype(np.uint8) * 255)
    save_grayscale(paths["truth"], truth_mask)
    save_grayscale(paths["filtered"], processed.filtered_image)
    save_grayscale(paths["adaptive"], processed.adaptive_mask)
    save_grayscale(paths["baseline"], processed.baseline.mask)
    save_grayscale(paths["improved"], processed.improved.mask)
    save_color(paths["baseline_overlay"], processed.baseline.overlay)
    save_color(paths["improved_overlay"], processed.improved.overlay)

    regions = processed.baseline.regions + processed.improved.regions
    manifest = DIPArtifactManifest(
        artifact_id=f"{fingerprint.run_ids[0]}_{fingerprint.run_ids[-1]}_{settings.encoder_version}",
        pipeline_id="orders_daily",
        window_run_ids=fingerprint.run_ids,
        encoder_version=fingerprint.encoder_version,
        baseline_version=baseline_version,
        created_at=datetime.now(timezone.utc),
        raw_image_path=str(paths["raw"]),
        validity_mask_path=str(paths["validity"]),
        ground_truth_mask_path=str(paths["truth"]),
        filtered_image_path=str(paths["filtered"]),
        adaptive_mask_path=str(paths["adaptive"]),
        baseline_mask_path=str(paths["baseline"]),
        improved_mask_path=str(paths["improved"]),
        baseline_overlay_path=str(paths["baseline_overlay"]),
        improved_overlay_path=str(paths["improved_overlay"]),
        channel_map=fingerprint.channel_ids,
        run_map=fingerprint.run_ids,
        regions=regions,
        parameters={
            **settings.model_dump(mode="json"),
            "baseline_method": "global_otsu" if settings.threshold_method == "otsu" else "global_fixed",
            "improved_method": "adaptive_threshold_then_configured_morphology",
        },
        processing_duration_ms=processed.baseline.duration_ms + processed.improved.duration_ms,
        warnings=(
            (f"missing_telemetry_pixels:{int((~fingerprint.validity_mask).sum())}",)
            if not fingerprint.validity_mask.all()
            else ()
        ),
    )
    manifest_path = window_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_regions_csv(window_dir / "regions.csv", regions)
    return manifest_path


def _method_outputs(
    processed: DIPProcessingResult,
) -> Iterable[tuple[str, NDArray[np.uint8], float]]:
    yield "DIP-B0", processed.baseline.mask, processed.baseline.duration_ms
    yield "DIP-P1", processed.improved.mask, processed.improved.duration_ms


def _confusion_counts(
    predicted: NDArray[np.uint8],
    expected: NDArray[np.uint8],
    validity: NDArray[np.bool_],
) -> tuple[int, int, int, int]:
    predicted_positive = (predicted > 0) & validity
    expected_positive = (expected > 0) & validity
    true_positive = int(np.logical_and(predicted_positive, expected_positive).sum())
    false_positive = int(np.logical_and(predicted_positive, ~expected_positive & validity).sum())
    false_negative = int(np.logical_and(~predicted_positive & validity, expected_positive).sum())
    true_negative = int(np.logical_and(~predicted_positive & validity, ~expected_positive).sum())
    return true_positive, false_positive, false_negative, true_negative


def _region_confusion_counts(
    predicted_labels: NDArray[np.int32],
    truth_labels: NDArray[np.int32],
    minimum_iou: float,
) -> tuple[int, int, int, int, int, float]:
    predicted_ids = tuple(int(value) for value in np.unique(predicted_labels) if value != 0)
    truth_ids = tuple(int(value) for value in np.unique(truth_labels) if value != 0)
    predicted_sizes = {component_id: int((predicted_labels == component_id).sum()) for component_id in predicted_ids}
    truth_sizes = {component_id: int((truth_labels == component_id).sum()) for component_id in truth_ids}
    candidates: list[tuple[float, int, int]] = []
    for predicted_id in predicted_ids:
        predicted_mask = predicted_labels == predicted_id
        for truth_id in truth_ids:
            intersection = int(np.logical_and(predicted_mask, truth_labels == truth_id).sum())
            if not intersection:
                continue
            union = predicted_sizes[predicted_id] + truth_sizes[truth_id] - intersection
            iou = intersection / union
            if iou >= minimum_iou:
                candidates.append((iou, predicted_id, truth_id))
    candidates.sort(reverse=True)
    matched_predicted: set[int] = set()
    matched_truth: set[int] = set()
    matched_ious: list[float] = []
    for iou, predicted_id, truth_id in candidates:
        if predicted_id not in matched_predicted and truth_id not in matched_truth:
            matched_predicted.add(predicted_id)
            matched_truth.add(truth_id)
            matched_ious.append(iou)
    true_positive = len(matched_ious)
    false_positive = len(predicted_ids) - true_positive
    false_negative = len(truth_ids) - true_positive
    return (
        true_positive,
        false_positive,
        false_negative,
        len(predicted_ids),
        len(truth_ids),
        sum(matched_ious),
    )


def _region_metrics(
    method: str,
    counts: tuple[int, int, int, int, int, float],
    minimum_iou: float,
) -> RegionSegmentationMetrics:
    true_positive, false_positive, false_negative, predicted_count, truth_count, matched_iou_sum = counts
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    f1_denominator = 2 * true_positive + false_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = 2 * true_positive / f1_denominator if f1_denominator else 0.0
    mean_iou = matched_iou_sum / true_positive if true_positive else 0.0
    return RegionSegmentationMetrics(
        method=method,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        predicted_region_count=predicted_count,
        ground_truth_region_count=truth_count,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_matched_iou=mean_iou,
        iou_match_threshold=minimum_iou,
    )


def _metrics(method: str, counts: tuple[int, int, int, int]) -> SegmentationMetrics:
    true_positive, false_positive, false_negative, true_negative = counts
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    union = true_positive + false_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1_denominator = 2 * true_positive + false_positive + false_negative
    f1 = 2 * true_positive / f1_denominator if f1_denominator else 0.0
    iou = true_positive / union if union else 0.0
    return SegmentationMetrics(
        method=method,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        valid_pixel_count=sum(counts),
        ground_truth_positive_count=true_positive + false_negative,
        predicted_positive_count=true_positive + false_positive,
        precision=precision,
        recall=recall,
        f1=f1,
        iou=iou,
    )


def _add_counts(target: list[int], new_counts: tuple[int, int, int, int]) -> None:
    for index, count in enumerate(new_counts):
        target[index] += count


def _add_region_counts(
    target: list[int | float], new_counts: tuple[int, int, int, int, int, float]
) -> None:
    for index, count in enumerate(new_counts):
        target[index] += count


def _region_count_mapping(counts: tuple[int, int, int, int, int, float]) -> dict[str, int | float]:
    true_positive, false_positive, false_negative, predicted_count, truth_count, matched_iou_sum = counts
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "predicted_region_count": predicted_count,
        "ground_truth_region_count": truth_count,
        "matched_iou_sum": matched_iou_sum,
    }


def _write_metrics_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    records = list(rows)
    fieldnames = list(records[0]) if records else []
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(records)


def _write_regions_csv(path: Path, regions: tuple[DIPRegion, ...]) -> None:
    rows = [
        {
            **region.model_dump(mode="json", exclude={"run_ids", "channel_ids"}),
            "run_ids": ";".join(region.run_ids),
            "channel_ids": ";".join(region.channel_ids),
        }
        for region in regions
    ]
    _write_metrics_csv(path, rows)


def main() -> None:
    """Run the configured synthetic DIP benchmark and save its outputs."""

    settings = Settings()
    dataset = generate_synthetic_dataset(settings)
    write_synthetic_dataset(dataset, settings.resolved_data_output_dir)
    result = evaluate_dip(dataset, settings)
    print(f"DIP summary: {result.summary_path}")
    print(f"DIP artifacts: {settings.resolved_dip_artifact_dir}")


if __name__ == "__main__":
    main()
