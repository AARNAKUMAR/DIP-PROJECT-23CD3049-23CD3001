"""The sole owner of Data Quality Fingerprint encoding."""

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

from datagard.config import DIPSettings
from datagard.contracts import PipelineRun, SchemaField
from datagard.metadata import SchemaRegistry


@dataclass(frozen=True)
class BaselineProfile:
    """Channel-wise healthy median and robust deviation scale."""

    version: str
    centers: Mapping[str, float]
    scales: Mapping[str, float]


@dataclass(frozen=True)
class Fingerprint:
    """Encoded image and stable pixel-to-telemetry maps."""

    pixels: NDArray[np.uint8]
    validity_mask: NDArray[np.bool_]
    run_ids: tuple[str, ...]
    channel_ids: tuple[str, ...]
    baseline_version: str
    encoder_version: str


def fit_channel_baselines(
    training_runs: tuple[PipelineRun, ...],
    settings: DIPSettings,
    reference_schema: tuple[SchemaField, ...],
) -> BaselineProfile:
    """Fit fixed channel centers/scales using only the caller's training runs."""

    if not training_runs:
        raise ValueError("At least one training run is required to fit DQF baselines")

    centers: dict[str, float] = {}
    scales: dict[str, float] = {}
    for channel_id in settings.channel_order:
        values = [
            value
            for run in training_runs
            if (value := _channel_value(run, channel_id, reference_schema)) is not None
        ]
        if not values:
            raise ValueError(f"No valid training observations for DQF channel {channel_id}")
        center = float(np.median(np.asarray(values, dtype=np.float64)))
        mad = float(np.median(np.abs(np.asarray(values, dtype=np.float64) - center)))
        centers[channel_id] = center
        scales[channel_id] = max(mad, settings.scale_floor)

    return BaselineProfile(settings.baseline_version, centers, scales)


def encode_fingerprint(
    runs: tuple[PipelineRun, ...],
    settings: DIPSettings,
    baseline: BaselineProfile,
    reference_schema: tuple[SchemaField, ...],
) -> Fingerprint:
    """Map a chronological fixed-length run window to calibrated grayscale pixels."""

    ordered_runs = tuple(sorted(runs, key=lambda run: (run.started_at, run.run_id)))
    if len(ordered_runs) != settings.window_size:
        raise ValueError(f"Expected {settings.window_size} runs; received {len(ordered_runs)}")
    if len({run.run_id for run in ordered_runs}) != len(ordered_runs):
        raise ValueError("Fingerprint window contains duplicate run IDs")

    pixels = np.zeros((len(ordered_runs), len(settings.channel_order)), dtype=np.uint8)
    validity_mask = np.zeros(pixels.shape, dtype=np.bool_)
    for row_index, run in enumerate(ordered_runs):
        for column_index, channel_id in enumerate(settings.channel_order):
            value = _channel_value(run, channel_id, reference_schema)
            if value is None:
                continue
            center = baseline.centers[channel_id]
            scale = baseline.scales[channel_id]
            normalized_deviation = min(1.0, abs(value - center) / (settings.robust_scale_k * scale))
            pixels[row_index, column_index] = np.uint8(np.rint(255.0 * normalized_deviation))
            validity_mask[row_index, column_index] = True

    return Fingerprint(
        pixels=pixels,
        validity_mask=validity_mask,
        run_ids=tuple(run.run_id for run in ordered_runs),
        channel_ids=settings.channel_order,
        baseline_version=baseline.version,
        encoder_version=settings.encoder_version,
    )


def _channel_value(
    run: PipelineRun,
    channel_id: str,
    reference_schema: tuple[SchemaField, ...],
) -> float | None:
    if channel_id == "output_rows":
        return float(run.output_rows)
    if channel_id == "duration_ms":
        return float(run.duration_ms)
    if channel_id == "schema.change_count":
        diff = SchemaRegistry.diff(reference_schema, run.observed_schema)
        return float(len(diff.added) + len(diff.removed) + len(diff.renamed) + len(diff.type_changed))

    try:
        field_id, metric_id = channel_id.split(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError(f"Unsupported DQF channel format: {channel_id}") from exc
    field_metrics = run.field_metrics.get(field_id)
    if field_metrics is None or not field_metrics.telemetry_available:
        return None
    value = getattr(field_metrics, metric_id, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"DQF channel {channel_id} is not numeric")
    return float(value)
