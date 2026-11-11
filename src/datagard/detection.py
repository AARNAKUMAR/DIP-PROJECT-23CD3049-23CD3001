"""Primary Isolation Forest model and deterministic quality-rule baseline."""

import logging
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from datagard.config import DetectionSettings
from datagard.contracts import DetectionPrediction, QualityFinding

logger = logging.getLogger(__name__)


class IsolationForestDetector:
    """Fit and score the configured unsupervised anomaly model."""

    def __init__(self, settings: DetectionSettings) -> None:
        self._settings = settings
        self._model: Pipeline | None = None
        self._feature_names: tuple[str, ...] = ()

    @property
    def model_version(self) -> str:
        return self._settings.model_version

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    def fit(self, training_matrix: NDArray[np.float64], feature_names: tuple[str, ...]) -> None:
        """Fit scaler and Isolation Forest on the caller's normal training rows."""

        _validate_matrix(training_matrix)
        if training_matrix.shape[1] != len(feature_names):
            raise ValueError("Feature matrix width does not match feature_names")
        if not feature_names or len(set(feature_names)) != len(feature_names):
            raise ValueError("Feature names must be non-empty and unique")

        estimator = IsolationForest(
            n_estimators=self._settings.n_estimators,
            max_samples=self._settings.max_samples,
            contamination=self._settings.contamination,
            max_features=self._settings.max_features,
            bootstrap=self._settings.bootstrap,
            n_jobs=self._settings.n_jobs,
            random_state=self._settings.random_state,
        )
        self._model = Pipeline(
            [("scaler", StandardScaler()), ("isolation_forest", estimator)]
        )
        self._model.fit(training_matrix)
        self._feature_names = feature_names
        logger.info(
            "Isolation Forest fitted",
            extra={"model_version": self.model_version, "training_rows": training_matrix.shape[0]},
        )

    def score(self, matrix: NDArray[np.float64]) -> NDArray[np.float64]:
        """Return larger-is-more-anomalous scores; these are not probabilities."""

        if self._model is None:
            raise RuntimeError("Detector must be fitted before scoring")
        _validate_matrix(matrix)
        if matrix.shape[1] != len(self._feature_names):
            raise ValueError("Scoring feature width differs from fitted feature width")
        return -self._model.score_samples(matrix)

    def predict(self, matrix: NDArray[np.float64], threshold: float) -> NDArray[np.bool_]:
        """Apply a validation-selected anomaly-score threshold."""

        return self.score(matrix) >= threshold

    def predictions(
        self,
        run_ids: tuple[str, ...],
        scores: NDArray[np.float64],
        threshold: float,
        evidence_refs: tuple[tuple[str, ...], ...],
    ) -> tuple[DetectionPrediction, ...]:
        """Build typed per-run predictions with finding references."""

        if len(run_ids) != len(scores) or len(run_ids) != len(evidence_refs):
            raise ValueError("Run IDs, scores, and evidence references must have matching lengths")
        return tuple(
            DetectionPrediction(
                run_id=run_id,
                anomaly_score=float(score),
                is_anomaly=bool(score >= threshold),
                model_version=self.model_version,
                threshold=threshold,
                evidence_refs=refs,
            )
            for run_id, score, refs in zip(run_ids, scores, evidence_refs, strict=True)
        )

    def save(self, path: Path) -> None:
        """Save the fitted estimator and exact feature contract locally."""

        if self._model is None:
            raise RuntimeError("Detector must be fitted before saving")
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self._model,
                "feature_names": self._feature_names,
                "model_version": self.model_version,
                "settings": self._settings.model_dump(mode="json"),
            },
            path,
        )


def rule_baseline_is_anomaly(
    findings: Iterable[QualityFinding],
    configured_severities: tuple[str, ...],
) -> bool:
    """Flag a run if its sole structured quality findings meet baseline severity."""

    severity_policy = set(configured_severities)
    return any(finding.severity in severity_policy for finding in findings)


def _validate_matrix(matrix: NDArray[np.float64]) -> None:
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("Feature matrix must be a non-empty 2D array")
    if not np.isfinite(matrix).all():
        raise ValueError("Feature matrix contains non-finite values")
