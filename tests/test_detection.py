"""CP-4 thresholding, grouped split, model artifact, and benchmark tests."""

import csv
import json

import joblib
import numpy as np

from datagard.config import get_settings
from datagard.detection import IsolationForestDetector
from datagard.evaluation import evaluate_detection, select_f1_threshold
from datagard.ingestion import generate_synthetic_dataset
from datagard.splits import split_by_incident_group


def test_threshold_is_selected_from_validation_scores() -> None:
    threshold, validation_f1 = select_f1_threshold(
        np.asarray([False, False, True, True]),
        np.asarray([0.1, 0.2, 0.3, 0.4]),
    )

    assert threshold == 0.3
    assert validation_f1 == 1.0


def test_grouped_split_keeps_scenario_episodes_intact() -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    label_map = {truth.run_id: truth for truth in dataset.labels}
    split = split_by_incident_group(
        dataset.runs,
        label_map,
        settings.evaluation.training_group_fraction,
        settings.evaluation.validation_group_fraction,
    )

    assert len(split.training_runs) == 216
    assert len(split.validation_runs) == 72
    assert len(split.test_runs) == 72
    assert set(split.training_group_ids).isdisjoint(split.validation_group_ids)
    assert set(split.training_group_ids).isdisjoint(split.test_group_ids)
    assert set(split.validation_group_ids).isdisjoint(split.test_group_ids)


def test_isolation_forest_scores_and_persists_feature_contract(tmp_path) -> None:
    settings = get_settings()
    detector = IsolationForestDetector(settings.detection)
    training = np.asarray([[0.0, 1.0], [0.2, 1.1], [-0.1, 0.9], [0.1, 1.0]])
    scoring = np.asarray([[0.0, 1.0], [5.0, 8.0]])

    detector.fit(training, ("feature_a", "feature_b"))
    scores = detector.score(scoring)
    model_path = tmp_path / "model.joblib"
    detector.save(model_path)
    stored = joblib.load(model_path)

    assert scores.shape == (2,)
    assert np.isfinite(scores).all()
    assert stored["feature_names"] == ("feature_a", "feature_b")
    assert stored["model_version"] == settings.detection.model_version


def test_detector_benchmark_writes_predictions_confusions_and_ablation(tmp_path) -> None:
    settings = get_settings()
    dataset = generate_synthetic_dataset(settings)
    output_dir = tmp_path / "evaluation"
    model_dir = tmp_path / "models"

    result = evaluate_detection(dataset, settings, output_dir, model_dir)

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["training_run_count"] == 216
    assert summary["validation_run_count"] == 72
    assert summary["test_run_count"] == 72
    assert summary["training_clean_run_count"] >= 2
    assert summary["split"]["train_validation_group_overlap"] == []
    assert summary["split"]["train_test_group_overlap"] == []
    assert summary["split"]["validation_test_group_overlap"] == []
    assert summary["ablation_run_counts"]["test"] > 0
    assert len(result.model_paths) == 3
    assert all(path.exists() for path in result.model_paths)
    assert result.confusion_matrices_path.exists()
    assert result.scenario_metrics_path.exists()

    with result.metrics_path.open(encoding="utf-8", newline="") as source:
        metric_rows = {row["detector_name"]: row for row in csv.DictReader(source)}
    assert set(metric_rows) == {
        "rule_baseline",
        "isolation_forest_structured",
        "ablation_structured_only",
        "ablation_structured_plus_dip",
    }
    assert metric_rows["rule_baseline"]["average_precision"] == ""
    assert float(metric_rows["isolation_forest_structured"]["average_precision"]) >= 0.0

    with result.predictions_path.open(encoding="utf-8", newline="") as source:
        prediction_rows = list(csv.DictReader(source))
    assert len(prediction_rows) == 72 * 2 + summary["ablation_run_counts"]["test"] * 2
    assert all(row["incident_group_id"] for row in prediction_rows)
