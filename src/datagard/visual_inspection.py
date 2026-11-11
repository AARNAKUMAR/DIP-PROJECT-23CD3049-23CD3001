"""Thin pipeline facade delegating to the dedicated DIP owners."""

from pathlib import Path

from datagard.config import Settings
from datagard.contracts import PipelineRun, SchemaField, SyntheticDataset
from datagard.dip.encoder import BaselineProfile, Fingerprint, encode_fingerprint, fit_channel_baselines
from datagard.dip.evaluation import DIPBenchmarkResult, evaluate_dip, main
from datagard.dip.processor import DIPProcessingResult, process_fingerprint


def encode_and_process_window(
    runs: tuple[PipelineRun, ...],
    settings: Settings,
    baseline: BaselineProfile,
    reference_schema: tuple[SchemaField, ...],
) -> tuple[Fingerprint, DIPProcessingResult]:
    """Compose the sole encoder and processor without owning image operations."""

    fingerprint = encode_fingerprint(runs, settings.dip, baseline, reference_schema)
    return fingerprint, process_fingerprint(fingerprint, settings.dip)


def run_dip_evaluation(
    dataset: SyntheticDataset,
    settings: Settings,
    artifact_dir: Path | None = None,
    evaluation_dir: Path | None = None,
) -> DIPBenchmarkResult:
    """Delegate artifact/evaluation work to the DIP evaluation module."""

    return evaluate_dip(dataset, settings, artifact_dir, evaluation_dir)


__all__ = [
    "BaselineProfile",
    "DIPBenchmarkResult",
    "DIPProcessingResult",
    "Fingerprint",
    "encode_and_process_window",
    "fit_channel_baselines",
    "run_dip_evaluation",
]


if __name__ == "__main__":
    main()
