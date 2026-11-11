"""CP-3 encoder, processor, mapping, and saved-evidence tests."""

import csv
import json

import cv2

from datagard.config import get_settings
from datagard.dip.encoder import encode_fingerprint, fit_channel_baselines
from datagard.dip.evaluation import evaluate_dip, ground_truth_mask
from datagard.dip.processor import process_fingerprint
from datagard.ingestion import generate_synthetic_dataset


def test_encoder_keeps_channel_order_and_missingness_explicit() -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    truths = {truth.run_id: truth for truth in dataset.labels}
    clean_runs = tuple(run for run in dataset.runs if truths[run.run_id].scenario_id == "clean")
    reference_schema = clean_runs[0].observed_schema
    baseline = fit_channel_baselines(clean_runs, settings.dip, reference_schema)
    missing_run = next(run for run in dataset.runs if truths[run.run_id].scenario_id == "missing_telemetry")
    window_runs = (missing_run, *(run for run in dataset.runs if run.run_id != missing_run.run_id))
    fingerprint = encode_fingerprint(window_runs[: settings.dip.window_size], settings.dip, baseline, reference_schema)

    assert fingerprint.pixels.shape == (settings.dip.window_size, len(settings.dip.channel_order))
    assert fingerprint.channel_ids == settings.dip.channel_order
    missing_row = fingerprint.run_ids.index(missing_run.run_id)
    amount_mean_column = fingerprint.channel_ids.index("amount.mean")
    assert not fingerprint.validity_mask[missing_row, amount_mean_column]


def test_processor_returns_two_mapped_masks_and_regions() -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    truth_by_run = {truth.run_id: truth for truth in dataset.labels}
    clean_runs = tuple(run for run in dataset.runs if truth_by_run[run.run_id].scenario_id == "clean")
    reference_schema = clean_runs[0].observed_schema
    baseline = fit_channel_baselines(clean_runs, settings.dip, reference_schema)
    window_runs = dataset.runs[: settings.dip.window_size]
    fingerprint = encode_fingerprint(window_runs, settings.dip, baseline, reference_schema)

    expected = ground_truth_mask(fingerprint, truth_by_run)
    result = process_fingerprint(fingerprint, settings.dip)

    assert expected.shape == result.baseline.mask.shape == result.improved.mask.shape
    assert result.baseline.method == "DIP-B0"
    assert result.improved.method == "DIP-P1"
    assert all(region.run_ids and region.channel_ids for region in result.baseline.regions + result.improved.regions)


def test_dip_benchmark_saves_images_regions_metrics_and_group_split(tmp_path) -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    artifacts = tmp_path / "fingerprints"
    evaluation = tmp_path / "evaluation"

    result = evaluate_dip(dataset, settings, artifacts, evaluation)

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["evaluated_window_count"] == len(result.manifest_paths)
    assert summary["evaluated_unique_run_count"] == 90
    assert summary["held_out_run_count"] == 108
    assert summary["window_coverage_fraction"] == 90 / 108
    assert set(summary["aggregate_metrics"]) == {"DIP-B0", "DIP-P1"}
    for method_metrics in summary["aggregate_metrics"].values():
        confusion_total = sum(
            method_metrics[key]
            for key in ("true_positive", "false_positive", "false_negative", "true_negative")
        )
        assert method_metrics["valid_pixel_count"] == confusion_total == 1024
    assert set(summary["split"]["training_group_ids"]).isdisjoint(summary["split"]["evaluation_group_ids"])
    assert result.aggregate_metrics_path.exists()
    assert result.region_metrics_path.exists()
    assert result.scenario_metrics_path.exists()
    assert (evaluation / "dip_window_metrics.csv").exists()
    with result.aggregate_metrics_path.open(encoding="utf-8", newline="") as metrics_file:
        metrics_rows = list(csv.DictReader(metrics_file))
    assert {row["method"] for row in metrics_rows} == {"DIP-B0", "DIP-P1"}
    region_metrics_rows = list(csv.DictReader(result.region_metrics_path.open(encoding="utf-8", newline="")))
    assert {row["method"] for row in region_metrics_rows} == {"DIP-B0", "DIP-P1"}
    for row in region_metrics_rows:
        assert int(row["predicted_region_count"]) == int(row["true_positive"]) + int(row["false_positive"])
        assert int(row["ground_truth_region_count"]) == int(row["true_positive"]) + int(row["false_negative"])
    assert (evaluation / "dip_region_window_metrics.csv").exists()

    manifest = json.loads(result.manifest_paths[0].read_text(encoding="utf-8"))
    assert len(manifest["run_map"]) == settings.dip.window_size
    assert len(manifest["channel_map"]) == len(settings.dip.channel_order)
    for image_key in (
        "raw_image_path", "validity_mask_path", "ground_truth_mask_path", "filtered_image_path",
        "adaptive_mask_path", "baseline_mask_path", "improved_mask_path", "baseline_overlay_path",
        "improved_overlay_path",
    ):
        image_path = artifacts.parent.parent / manifest[image_key]
        assert image_path.exists()
        image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        assert image is not None
