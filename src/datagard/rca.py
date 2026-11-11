"""Evidence-grounded, rule-assisted root-cause hypotheses."""

from datagard.config import RCASettings
from datagard.contracts import DIPRegion, PipelineRun, QualityFinding, RCAHypothesis, SchemaField
from datagard.metadata import LineageGraph, SchemaRegistry


def investigate_run(
    run: PipelineRun,
    expected_schema: tuple[SchemaField, ...],
    findings: tuple[QualityFinding, ...],
    lineage: LineageGraph,
    recent_runs: tuple[PipelineRun, ...] = (),
    dip_regions: tuple[DIPRegion, ...] = (),
    settings: RCASettings | None = None,
) -> tuple[RCAHypothesis, ...]:
    """Rank candidate causes from observed evidence; return no claim without support."""

    by_rule: dict[str, list[QualityFinding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)
    hypotheses: list[tuple[int, RCAHypothesis]] = []
    upstream = lineage.upstream_of(run.pipeline_id)
    downstream = lineage.downstream_of(run.pipeline_id)
    schema_diff = SchemaRegistry.diff(expected_schema, run.observed_schema)
    schema_evidence = tuple(
        finding.finding_id
        for finding in findings
        if finding.rule_id.startswith("SCHEMA_")
    )
    if schema_evidence or schema_diff.added or schema_diff.removed or schema_diff.renamed or schema_diff.type_changed:
        hypotheses.append((
            0,
            _hypothesis(
                "SCHEMA_DRIFT",
                "Observed schema differs from the registered schema.",
                schema_evidence,
                (f"schema_diff={schema_diff}",),
                upstream,
                downstream,
                "Review changed fields and confirm producer/consumer compatibility.",
            ),
        ))

    for rule_id, code, summary, next_step in (
        ("ROW_COUNT_DROP", "UPSTREAM_VOLUME_DROP", "Output row count fell relative to input.", "Inspect upstream run status and source volume before considering a rerun."),
        ("NULL_RATE_MAX", "SOURCE_NULL_SURGE", "Null rate exceeded the configured field threshold.", "Compare source payload and mapping history for the affected field."),
        ("DUPLICATE_RATE_MAX", "DUPLICATE_KEY_GENERATION", "Duplicate key rate exceeded its configured threshold.", "Inspect key generation and deduplication behavior in the source and transform."),
        ("DISTRIBUTION_SHIFT", "SOURCE_OR_TRANSFORM_SHIFT", "A field distribution differs from its supplied history baseline.", "Compare source population and transformation versions against recent runs."),
        ("INVALID_RANGE", "OUT_OF_RANGE_VALUES", "Observed values exceeded the configured field range.", "Inspect source values and the transformation that populated the affected field."),
    ):
        evidence = tuple(finding.finding_id for finding in by_rule.get(rule_id, []))
        if evidence:
            missing = _history_context(run, recent_runs)
            hypotheses.append((len(evidence), _hypothesis(code, summary, evidence, missing, upstream, downstream, next_step)))

    failed = tuple(finding.finding_id for finding in by_rule.get("PIPELINE_FAILED", []))
    if failed:
        hypotheses.append((
            len(failed),
            _hypothesis(
                "EXECUTION_OR_RESOURCE_FAILURE",
                "The pipeline run reported failure; runtime or dependency evidence should be checked.",
                failed,
                _history_context(run, recent_runs),
                upstream,
                downstream,
                "Inspect stage logs and upstream completion before retrying the run.",
            ),
        ))

    runtime_baseline = tuple(item.duration_ms for item in recent_runs if item.pipeline_id == run.pipeline_id and item.run_id != run.run_id)
    if runtime_baseline and settings is not None:
        typical_duration = sorted(runtime_baseline)[len(runtime_baseline) // 2]
        if typical_duration > 0 and run.duration_ms / typical_duration > settings.runtime_spike_ratio:
            hypotheses.append((
                1,
                _hypothesis(
                    "EXECUTION_RESOURCE_OR_PARTITION",
                    "Run duration exceeded the configured ratio of recent pipeline history.",
                    (f"runtime:{run.run_id}",),
                    (f"recent_median_duration_ms={typical_duration}; status={run.status}",),
                    upstream,
                    downstream,
                    "Inspect stage timing, resource pressure, partition skew, and upstream completion.",
                ),
            ))

    missing_telemetry = tuple(finding.finding_id for finding in by_rule.get("TELEMETRY_MISSING", []))
    if missing_telemetry and not hypotheses:
        hypotheses.append((
            0,
            _hypothesis(
                "INCONCLUSIVE",
                "Telemetry is incomplete, so the available evidence does not support a specific cause.",
                missing_telemetry,
                ("Additional source, execution, or schema evidence is required.",),
                upstream,
                downstream,
                "Restore or inspect the missing telemetry before selecting a remediation.",
            ),
        ))

    if dip_regions:
        region_refs = tuple(f"dip:{region.method}:{region.component_id}" for region in dip_regions)
        hypotheses.append((
            0,
            _hypothesis(
                "VISUAL_TELEMETRY_PATTERN",
                "DIP detected a mapped visual region; this is supporting evidence, not a causal diagnosis.",
                region_refs,
                ("DIP regions identify telemetry coordinates but do not establish cause.",),
                upstream,
                downstream,
                "Inspect the mapped runs and channels alongside structured findings.",
            ),
        ))

    hypotheses.sort(key=lambda item: (-item[0], item[1].cause_code))
    return tuple(hypothesis.model_copy(update={"rank": rank}) for rank, (_, hypothesis) in enumerate(hypotheses, start=1))


def _hypothesis(
    cause_code: str,
    summary: str,
    evidence: tuple[str, ...],
    missing: tuple[str, ...],
    upstream: tuple[str, ...],
    downstream: tuple[str, ...],
    next_investigation: str,
) -> RCAHypothesis:
    return RCAHypothesis(
        cause_code=cause_code,
        summary=summary,
        rank=1,
        supporting_evidence_ids=tuple(sorted(evidence)),
        contradicting_or_missing_evidence=missing,
        upstream_nodes=upstream,
        downstream_nodes=downstream,
        next_investigation=next_investigation,
    )


def _history_context(run: PipelineRun, recent_runs: tuple[PipelineRun, ...]) -> tuple[str, ...]:
    related = tuple(item for item in recent_runs if item.pipeline_id == run.pipeline_id and item.run_id != run.run_id)
    if not related:
        return ("No comparable recent-run history supplied.",)
    baseline = sum(item.output_rows for item in related) / len(related)
    if run.output_rows < baseline:
        return (f"Recent output-row mean={baseline:.2f}; this run={run.output_rows}.",)
    return (f"Recent output-row mean={baseline:.2f}; this run is not below that baseline.",)
