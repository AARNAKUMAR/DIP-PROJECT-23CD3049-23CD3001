"""Canonical, validated domain contracts for pipeline run data."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Reject unknown fields at data boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemaField(StrictModel):
    """One field in an observed or registered pipeline schema."""

    field_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool
    is_key: bool


class FieldMetrics(StrictModel):
    """Available structured summary metrics for one field in a run."""

    null_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    distinct_count: int | None = Field(default=None, ge=0)
    mean: float | None = None
    standard_deviation: float | None = Field(default=None, ge=0.0)
    minimum: float | None = None
    maximum: float | None = None
    telemetry_available: bool = True


class PipelineRun(StrictModel):
    """Canonical representation of one pipeline execution."""

    run_id: str = Field(min_length=1)
    pipeline_id: str = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    status: Literal["SUCCESS", "FAILED"]
    input_rows: int = Field(ge=0)
    output_rows: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    schema_version: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    field_metrics: dict[str, FieldMetrics]
    observed_schema: tuple[SchemaField, ...]


class QualityFinding(StrictModel):
    """One structured quality observation with traceable source evidence."""

    finding_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    field_id: str | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    observed: float | int | str | None
    expected_or_baseline: float | int | str | None = None
    message: str = Field(min_length=1)
    evidence: dict[str, object]
    created_at: datetime


class FeatureVector(StrictModel):
    """A deterministic, named feature vector in canonical order."""

    feature_names: tuple[str, ...]
    values: tuple[float, ...]


class DIPRegion(StrictModel):
    """Connected visual region mapped to source runs and telemetry channels."""

    method: Literal["DIP-B0", "DIP-P1"]
    component_id: int = Field(ge=1)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    centroid_x: float
    centroid_y: float
    area: int = Field(ge=1)
    peak_intensity: int = Field(ge=0, le=255)
    density: float = Field(ge=0.0, le=1.0)
    run_ids: tuple[str, ...]
    channel_ids: tuple[str, ...]


class DIPArtifactManifest(StrictModel):
    """Persisted references and provenance for one processed fingerprint."""

    artifact_id: str = Field(min_length=1)
    pipeline_id: str = Field(min_length=1)
    window_run_ids: tuple[str, ...]
    encoder_version: str
    baseline_version: str
    created_at: datetime
    raw_image_path: str
    filtered_image_path: str
    adaptive_mask_path: str
    validity_mask_path: str
    ground_truth_mask_path: str
    baseline_mask_path: str
    improved_mask_path: str
    baseline_overlay_path: str
    improved_overlay_path: str
    channel_map: tuple[str, ...]
    run_map: tuple[str, ...]
    regions: tuple[DIPRegion, ...]
    parameters: dict[str, object]
    processing_duration_ms: float = Field(ge=0.0)
    warnings: tuple[str, ...] = ()


class SegmentationMetrics(StrictModel):
    """Pixel-level binary segmentation metrics and their denominators."""

    method: Literal["DIP-B0", "DIP-P1"]
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    valid_pixel_count: int = Field(ge=0)
    ground_truth_positive_count: int = Field(ge=0)
    predicted_positive_count: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    iou: float = Field(ge=0.0, le=1.0)


class DetectionPrediction(StrictModel):
    """One detector output with a trace back to quality evidence."""

    run_id: str = Field(min_length=1)
    anomaly_score: float
    is_anomaly: bool
    model_version: str = Field(min_length=1)
    threshold: float
    evidence_refs: tuple[str, ...] = ()


class DetectionMetrics(StrictModel):
    """Binary detector metrics and explicit sample/confusion denominators."""

    detector_name: str
    sample_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    average_precision: float | None = Field(default=None, ge=0.0, le=1.0)


class Incident(StrictModel):
    """Deduplicated incident created from detector output and run evidence."""

    incident_id: str = Field(min_length=1)
    pipeline_id: str = Field(min_length=1)
    affected_run_id: str = Field(min_length=1)
    incident_family: str = Field(min_length=1)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    status: Literal["OPEN", "INVESTIGATING", "RESOLVED", "ESCALATED"]
    detected_at: datetime
    evidence_refs: tuple[str, ...]
    detector_version: str


class RCAHypothesis(StrictModel):
    """Ranked causal hypothesis with explicit supporting and missing evidence."""

    cause_code: str
    summary: str
    rank: int = Field(ge=1)
    supporting_evidence_ids: tuple[str, ...]
    contradicting_or_missing_evidence: tuple[str, ...] = ()
    upstream_nodes: tuple[str, ...] = ()
    downstream_nodes: tuple[str, ...] = ()
    next_investigation: str


class RunbookChunk(StrictModel):
    """Stable local runbook section returned by lexical retrieval."""

    document_id: str
    section_id: str
    title: str
    score: float = Field(ge=0.0)
    text: str


class ActionProposal(StrictModel):
    """Allowlisted remediation proposal with explicit policy fields."""

    action_id: str
    incident_id: str
    tool_name: Literal["quarantine_batch", "simulate_rerun", "simulate_repair", "escalate_incident", "release_batch"]
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    preconditions: tuple[str, ...]
    expected_outcome: str
    evidence_refs: tuple[str, ...]
    runbook_refs: tuple[str, ...]
    requires_approval: bool


class ApprovalRecord(StrictModel):
    """Simulated human approval attached to one proposed action."""

    approval_id: str
    action_id: str
    decision: Literal["APPROVED", "REJECTED"]
    approver_role: str
    reason: str
    decided_at: datetime


class ToolAuditEvent(StrictModel):
    """Application audit event for a typed tool invocation."""

    event_id: str
    correlation_id: str
    incident_id: str
    tool_name: str
    idempotency_key: str
    status: Literal["SUCCEEDED", "REJECTED", "FAILED"]
    detail: str
    occurred_at: datetime


class VerificationResult(StrictModel):
    """Quality recheck result for an original or simulated output record."""

    run_id: str
    passed: bool
    finding_ids: tuple[str, ...]
    quarantine_state: Literal["TRUSTED", "QUARANTINED"]
    summary: str


class AgentState(StrictModel):
    """Typed state owned and transitioned only by the agent orchestrator."""

    incident_id: str
    run_id: str
    goal: str
    current_status: Literal[
        "NEW", "INVESTIGATING", "PROPOSED", "AWAITING_APPROVAL", "READY_TO_EXECUTE",
        "EXECUTING", "VERIFYING", "RESOLVED", "ESCALATED", "FAILED",
    ]
    findings: tuple[QualityFinding, ...] = ()
    anomaly_result: DetectionPrediction | None = None
    rca_hypotheses: tuple[RCAHypothesis, ...] = ()
    retrieved_runbook_refs: tuple[str, ...] = ()
    action_proposals: tuple[ActionProposal, ...] = ()
    approval_status: Literal["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"] = "NOT_REQUIRED"
    executed_action_ids: tuple[str, ...] = ()
    verification_result: VerificationResult | None = None
    feedback: str | None = None
    correlation_id: str


class AgentTransition(StrictModel):
    """Auditable state-machine transition owned by the orchestrator."""

    incident_id: str
    correlation_id: str
    from_status: str
    to_status: str
    reason: str
    occurred_at: datetime


class InspectPipelineInput(StrictModel):
    run_id: str
    incident_id: str | None = None


class RetrieveRunbookInput(StrictModel):
    query: str = Field(min_length=1)
    incident_id: str | None = None


class IncidentActionInput(StrictModel):
    incident_id: str
    idempotency_key: str = Field(min_length=1)


class ReleaseBatchInput(IncidentActionInput):
    verification_run_id: str


class RerunInput(IncidentActionInput):
    pass


class RepairInput(IncidentActionInput):
    approval_id: str
    action_id: str
    repair_kind: Literal["align_schema"]


class EscalateInput(IncidentActionInput):
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...]


class ApprovalInput(StrictModel):
    action_id: str
    decision: Literal["APPROVED", "REJECTED"]
    approver_role: str
    reason: str = Field(min_length=1)


class ToolRequest(StrictModel):
    """A registered tool name paired with one validated payload type."""

    tool_name: Literal[
        "inspect_pipeline", "retrieve_runbook", "quarantine_batch", "simulate_rerun",
        "simulate_repair", "escalate_incident", "record_approval", "release_batch",
    ]
    payload: InspectPipelineInput | RetrieveRunbookInput | RepairInput | EscalateInput | ReleaseBatchInput | RerunInput | IncidentActionInput | ApprovalInput


class ToolResult(StrictModel):
    """Typed result envelope returned by the registered tool boundary."""

    tool_name: str
    status: Literal["SUCCEEDED", "REJECTED", "FAILED"]
    data: dict[str, object]


class RegionSegmentationMetrics(StrictModel):
    """Connected-component detection scores with one-to-one IoU matching."""

    method: Literal["DIP-B0", "DIP-P1"]
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    predicted_region_count: int = Field(ge=0)
    ground_truth_region_count: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    mean_matched_iou: float = Field(ge=0.0, le=1.0)
    iou_match_threshold: float = Field(gt=0.0, le=1.0)


class ScenarioTruth(StrictModel):
    """Ground truth kept in a separate artifact from model input fields."""

    run_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    incident_group_id: str = Field(min_length=1)
    is_incident: bool
    incident_start_at: datetime | None = None


class SyntheticDataset(StrictModel):
    """Generated telemetry and separately represented evaluation truth."""

    runs: tuple[PipelineRun, ...]
    labels: tuple[ScenarioTruth, ...]
