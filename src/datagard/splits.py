"""Single owner of deterministic incident-group train/validation/test splits."""

from dataclasses import dataclass

from datagard.contracts import PipelineRun, ScenarioTruth


@dataclass(frozen=True)
class GroupedDataSplit:
    """Runs and group IDs assigned to three chronological partitions."""

    training_runs: tuple[PipelineRun, ...]
    validation_runs: tuple[PipelineRun, ...]
    test_runs: tuple[PipelineRun, ...]
    training_group_ids: tuple[str, ...]
    validation_group_ids: tuple[str, ...]
    test_group_ids: tuple[str, ...]


def split_by_incident_group(
    runs: tuple[PipelineRun, ...],
    labels_by_run_id: dict[str, ScenarioTruth],
    training_fraction: float,
    validation_fraction: float = 0.0,
) -> GroupedDataSplit:
    """Split chronological contiguous incident groups without group leakage."""

    if not 0.0 < training_fraction < 1.0:
        raise ValueError("training_fraction must be between zero and one")
    if validation_fraction < 0.0 or training_fraction + validation_fraction >= 1.0:
        raise ValueError("Split fractions must leave a non-empty test partition")

    ordered_groups: list[str] = []
    for run in sorted(runs, key=lambda item: (item.started_at, item.run_id)):
        group_id = labels_by_run_id[run.run_id].incident_group_id
        if not ordered_groups or ordered_groups[-1] != group_id:
            if group_id in ordered_groups:
                raise ValueError(f"Incident group {group_id} is not contiguous in run chronology")
            ordered_groups.append(group_id)

    training_group_count = int(len(ordered_groups) * training_fraction)
    validation_group_count = int(len(ordered_groups) * validation_fraction)
    test_start = training_group_count + validation_group_count
    if (
        training_group_count <= 0
        or (validation_fraction > 0.0 and validation_group_count <= 0)
        or test_start >= len(ordered_groups)
    ):
        raise ValueError("Grouped split does not contain all requested non-empty partitions")

    training_groups = tuple(ordered_groups[:training_group_count])
    validation_groups = tuple(ordered_groups[training_group_count:test_start])
    test_groups = tuple(ordered_groups[test_start:])
    training_group_set = set(training_groups)
    validation_group_set = set(validation_groups)
    test_group_set = set(test_groups)
    ordered_runs = tuple(sorted(runs, key=lambda item: (item.started_at, item.run_id)))
    return GroupedDataSplit(
        training_runs=tuple(run for run in ordered_runs if labels_by_run_id[run.run_id].incident_group_id in training_group_set),
        validation_runs=tuple(run for run in ordered_runs if labels_by_run_id[run.run_id].incident_group_id in validation_group_set),
        test_runs=tuple(run for run in ordered_runs if labels_by_run_id[run.run_id].incident_group_id in test_group_set),
        training_group_ids=training_groups,
        validation_group_ids=validation_groups,
        test_group_ids=test_groups,
    )
