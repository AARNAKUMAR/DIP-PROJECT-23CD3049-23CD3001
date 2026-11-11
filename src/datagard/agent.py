"""Single deterministic coordinator and validated incident workflow state machine."""

import logging
import uuid
from datetime import datetime, timezone

from datagard.config import Settings
from datagard.contracts import (
    ActionProposal,
    AgentState,
    AgentTransition,
    ApprovalInput,
    DetectionPrediction,
    EscalateInput,
    Incident,
    IncidentActionInput,
    InspectPipelineInput,
    PipelineRun,
    QualityFinding,
    RCAHypothesis,
    RepairInput,
    ReleaseBatchInput,
    RetrieveRunbookInput,
    RerunInput,
    SchemaField,
    ToolRequest,
    VerificationResult,
)
from datagard.contracts import DIPRegion
from datagard.metadata import LineageGraph
from datagard.rca import investigate_run
from datagard.tools import ToolRegistry

logger = logging.getLogger(__name__)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"INVESTIGATING", "FAILED"}),
    "INVESTIGATING": frozenset({"PROPOSED", "ESCALATED", "FAILED"}),
    "PROPOSED": frozenset({"AWAITING_APPROVAL", "READY_TO_EXECUTE", "ESCALATED", "FAILED"}),
    "AWAITING_APPROVAL": frozenset({"READY_TO_EXECUTE", "ESCALATED", "FAILED"}),
    "READY_TO_EXECUTE": frozenset({"EXECUTING", "FAILED"}),
    "EXECUTING": frozenset({"VERIFYING", "FAILED"}),
    "VERIFYING": frozenset({"PROPOSED", "RESOLVED", "ESCALATED", "FAILED"}),
}


class AgentOrchestrator:
    """Own investigation sequence, action planning, approvals, and state transitions."""

    def __init__(self, settings: Settings, tools: ToolRegistry) -> None:
        self._settings = settings
        self._tools = tools
        self._state: AgentState | None = None
        self._transitions: list[AgentTransition] = []
        self._selected_action: ActionProposal | None = None
        self._approval_id: str | None = None

    def restore(self, state: AgentState, transitions: tuple[AgentTransition, ...]) -> None:
        """Restore a persisted workflow snapshot when the application restarts."""

        if self._state is not None:
            raise RuntimeError("Cannot restore over a running workflow")
        self._state = state
        self._transitions.extend(transitions)
        if state.current_status == "AWAITING_APPROVAL":
            self._selected_action = next(
                (item for item in state.action_proposals if item.requires_approval and item.action_id not in state.executed_action_ids),
                None,
            )
            if self._selected_action is not None:
                approval = self._tools.approval_for_action(self._selected_action.action_id)
                self._approval_id = approval.approval_id if approval and approval.decision == "APPROVED" else None

    def export_state(self) -> dict[str, object]:
        """Return current state and transitions as JSON-compatible data."""

        return {
            "state": self.state.model_dump(mode="json"),
            "transitions": [item.model_dump(mode="json") for item in self._transitions],
            "approval_id": self._approval_id,
        }

    @property
    def state(self) -> AgentState:
        if self._state is None:
            raise RuntimeError("Agent workflow has not started")
        return self._state

    @property
    def transitions(self) -> tuple[AgentTransition, ...]:
        return tuple(self._transitions)

    def investigate(
        self,
        incident: Incident,
        run: PipelineRun,
        findings: tuple[QualityFinding, ...],
        expected_schema: tuple[SchemaField, ...],
        lineage: LineageGraph,
        recent_runs: tuple[PipelineRun, ...],
        runbook_query: str,
        *,
        anomaly_result: DetectionPrediction | None = None,
        dip_regions: tuple[DIPRegion, ...] = (),
    ) -> AgentState:
        """Inspect, rank RCA, retrieve runbook evidence, and propose allowlisted actions."""

        if self._state is not None:
            raise RuntimeError("This orchestrator instance owns one incident workflow")
        if incident.affected_run_id != run.run_id or incident.pipeline_id != run.pipeline_id:
            raise ValueError("Incident and run identifiers do not match")
        correlation_id = str(uuid.uuid4())
        self._state = AgentState(
            incident_id=incident.incident_id,
            run_id=run.run_id,
            goal="Investigate the incident and respond without modifying source data.",
            current_status="NEW",
            findings=findings,
            anomaly_result=anomaly_result,
            rca_hypotheses=(),
            correlation_id=correlation_id,
        )
        self._transition("INVESTIGATING", "Begin evidence collection")
        inspection = self._tools.execute(
            ToolRequest(tool_name="inspect_pipeline", payload=InspectPipelineInput(run_id=run.run_id, incident_id=incident.incident_id)),
            correlation_id,
        )
        if inspection.status != "SUCCEEDED":
            self._transition("FAILED", "Pipeline inspection tool failed")
            return self.state
        hypotheses = investigate_run(
            run, expected_schema, findings, lineage, recent_runs, dip_regions, self._settings.rca
        )
        retrieved = self._tools.execute(
            ToolRequest(tool_name="retrieve_runbook", payload=RetrieveRunbookInput(query=runbook_query, incident_id=incident.incident_id)),
            correlation_id,
        )
        if retrieved.status != "SUCCEEDED":
            self._transition("FAILED", "Runbook retrieval tool failed")
            return self.state.model_copy(update={"rca_hypotheses": hypotheses})
        chunks = retrieved.data.get("chunks", [])
        refs = tuple(str(item["section_id"]) for item in chunks if isinstance(item, dict))
        proposals = self._plan_actions(incident, findings, refs)
        self._state = self.state.model_copy(update={
            "rca_hypotheses": hypotheses,
            "retrieved_runbook_refs": refs,
            "action_proposals": proposals,
        })
        if not hypotheses:
            self._transition("ESCALATED", "Insufficient evidence for a supported causal hypothesis")
        else:
            self._transition("PROPOSED", "Evidence bundle and allowlisted plan are ready")
        return self.state

    def execute_action(self, action_id: str) -> AgentState:
        """Execute only the currently selected proposal through the tool registry."""

        proposal = next((item for item in self.state.action_proposals if item.action_id == action_id), None)
        if proposal is None:
            raise ValueError("Action proposal does not exist in this workflow")
        if self.state.current_status not in {"PROPOSED", "AWAITING_APPROVAL"}:
            raise ValueError(f"Cannot execute an action while status is {self.state.current_status}")
        self._selected_action = proposal
        if proposal.requires_approval and self._approval_id is None:
            if self.state.current_status == "PROPOSED":
                self._transition("AWAITING_APPROVAL", "Policy requires explicit approval for this action")
            self._state = self.state.model_copy(update={"approval_status": "PENDING"})
            return self.state
        if self.state.current_status == "AWAITING_APPROVAL" and self.state.approval_status != "APPROVED":
            raise PermissionError("Approval must be recorded before execution")
        self._transition("READY_TO_EXECUTE", "Action preconditions are satisfied")
        self._transition("EXECUTING", "Dispatching through registered tool boundary")
        request = self._action_request(proposal)
        result = self._tools.execute(request, self.state.correlation_id)
        if result.status != "SUCCEEDED":
            self._transition("FAILED", str(result.data.get("reason", "Tool execution failed")))
            self._state = self.state.model_copy(update={"feedback": str(result.data.get("reason", "Tool execution failed"))})
            return self.state
        self._transition("VERIFYING", "Rechecking the resulting state or output")
        verification = _verification(proposal, result.data, self.state.run_id)
        self._state = self.state.model_copy(update={
            "executed_action_ids": self.state.executed_action_ids + (proposal.action_id,),
            "verification_result": verification,
        })
        remaining = tuple(
            item for item in self.state.action_proposals
            if item.action_id not in self.state.executed_action_ids
        )
        if not verification.passed and proposal.tool_name in {"simulate_repair", "release_batch"}:
            self._transition("ESCALATED", "Post-action quality or trust verification failed")
        elif remaining:
            self._transition("PROPOSED", "Verified this action; the next allowlisted plan step is ready")
        elif verification.passed and proposal.tool_name in {"simulate_repair", "release_batch"}:
            self._transition("RESOLVED", "Separate repaired artifact passed configured quality verification")
        else:
            self._transition("ESCALATED", "Action was recorded; source defect remains or requires human review")
        return self.state

    def record_approval(self, decision: str, role: str, reason: str) -> AgentState:
        """Record reviewer decision through the registered approval tool."""

        if self.state.current_status != "AWAITING_APPROVAL" or self._selected_action is None:
            raise ValueError("No action is currently awaiting approval")
        result = self._tools.execute(ToolRequest(
            tool_name="record_approval",
            payload=ApprovalInput(
                action_id=self._selected_action.action_id,
                decision=decision,  # validated by the strict request contract
                approver_role=role,
                reason=reason,
            ),
        ), self.state.correlation_id)
        if result.status != "SUCCEEDED":
            return self.state.model_copy(update={"approval_status": "REJECTED", "feedback": str(result.data.get("reason"))})
        self._approval_id = str(result.data["approval_id"])
        if decision == "APPROVED":
            self._state = self.state.model_copy(update={"approval_status": "APPROVED"})
        else:
            self._state = self.state.model_copy(update={"approval_status": "REJECTED"})
            self._transition("ESCALATED", "Reviewer rejected the proposed high-risk action")
        return self.state

    def _plan_actions(
        self,
        incident: Incident,
        findings: tuple[QualityFinding, ...],
        runbook_refs: tuple[str, ...],
    ) -> tuple[ActionProposal, ...]:
        tools = ["quarantine_batch"]
        if incident.incident_family == "SCHEMA_DRIFT":
            tools.extend(("simulate_repair", "release_batch"))
        else:
            tools.append("simulate_rerun")
        descriptions = {
            "quarantine_batch": ("LOW", "Prevent consumers from trusting the affected batch."),
            "simulate_rerun": ("LOW", "Create a separate simulated run and recheck quality."),
            "simulate_repair": ("HIGH", "Create a separate schema-aligned artifact and recheck quality."),
            "release_batch": ("LOW", "Restore batch trust only after a passing post-action verification."),
        }
        proposals: list[ActionProposal] = []
        for tool_name in tools:
            risk, expected = descriptions[tool_name]
            action_id = f"{incident.incident_id}:{tool_name}"
            proposals.append(ActionProposal(
                action_id=action_id,
                incident_id=incident.incident_id,
                tool_name=tool_name,
                risk_level=risk,
                preconditions=("incident is open", "affected local run exists"),
                expected_outcome=expected,
                evidence_refs=tuple(sorted(set(incident.evidence_refs + tuple(finding.finding_id for finding in findings)))),
                runbook_refs=runbook_refs,
                requires_approval=tool_name in self._settings.actions.approval_required_tools,
            ))
        return tuple(proposals)

    def _action_request(self, proposal: ActionProposal) -> ToolRequest:
        idempotency_key = proposal.action_id
        if proposal.tool_name == "quarantine_batch":
            return ToolRequest(tool_name=proposal.tool_name, payload=IncidentActionInput(
                incident_id=proposal.incident_id, idempotency_key=idempotency_key
            ))
        if proposal.tool_name == "simulate_rerun":
            return ToolRequest(tool_name=proposal.tool_name, payload=RerunInput(
                incident_id=proposal.incident_id, idempotency_key=idempotency_key
            ))
        if proposal.tool_name == "simulate_repair" and self._approval_id:
            return ToolRequest(tool_name=proposal.tool_name, payload=RepairInput(
                incident_id=proposal.incident_id,
                idempotency_key=idempotency_key,
                approval_id=self._approval_id,
                action_id=proposal.action_id,
                repair_kind="align_schema",
            ))
        if proposal.tool_name == "release_batch" and self.state.verification_result is not None:
            return ToolRequest(tool_name=proposal.tool_name, payload=ReleaseBatchInput(
                incident_id=proposal.incident_id,
                idempotency_key=idempotency_key,
                verification_run_id=self.state.verification_result.run_id,
            ))
        if proposal.tool_name == "escalate_incident":
            return ToolRequest(tool_name=proposal.tool_name, payload=EscalateInput(
                incident_id=proposal.incident_id,
                idempotency_key=idempotency_key,
                reason="The evidence is inconclusive or risk requires human review.",
                evidence_refs=proposal.evidence_refs,
            ))
        raise ValueError("No registered request mapping exists for the proposed action")

    def _transition(self, to_status: str, reason: str) -> None:
        current = self.state.current_status
        if to_status not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise ValueError(f"Invalid agent state transition: {current} -> {to_status}")
        self._transitions.append(AgentTransition(
            incident_id=self.state.incident_id,
            correlation_id=self.state.correlation_id,
            from_status=current,
            to_status=to_status,
            reason=reason,
            occurred_at=datetime.now(timezone.utc),
        ))
        self._state = self.state.model_copy(update={"current_status": to_status})
        logger.info("agent state transitioned", extra={"incident_id": self.state.incident_id, "from_status": current, "to_status": to_status})


def _verification(proposal: ActionProposal, data: dict[str, object], source_run_id: str) -> VerificationResult:
    if proposal.tool_name == "quarantine_batch":
        passed = data.get("batch_state") == "QUARANTINED"
        return VerificationResult(
            run_id=source_run_id,
            passed=passed,
            finding_ids=proposal.evidence_refs,
            quarantine_state="QUARANTINED" if passed else "TRUSTED",
            summary="Quarantine state confirmed; source data remains unchanged.",
        )
    if proposal.tool_name == "simulate_rerun":
        finding_ids = tuple(str(item) for item in data.get("finding_ids", []))
        return VerificationResult(
            run_id=str(data.get("simulated_run", {}).get("run_id", source_run_id)),
            passed=bool(data.get("verified")),
            finding_ids=finding_ids,
            quarantine_state="QUARANTINED",
            summary="Simulated output passed quality checks." if data.get("verified") else "Simulated rerun retains quality findings; incident remains open for review.",
        )
    if proposal.tool_name == "simulate_repair":
        finding_ids = tuple(str(item) for item in data.get("remaining_finding_ids", []))
        return VerificationResult(
            run_id=str(data.get("repaired_run", {}).get("run_id", source_run_id)),
            passed=bool(data.get("quality_verified")) and not finding_ids,
            finding_ids=finding_ids,
            quarantine_state="QUARANTINED",
            summary="Schema contract verified on a separate artifact; original remains quarantined.",
        )
    if proposal.tool_name == "release_batch":
        passed = data.get("batch_state") == "TRUSTED"
        return VerificationResult(
            run_id=str(data.get("verification_run_id", source_run_id)),
            passed=passed,
            finding_ids=(),
            quarantine_state="TRUSTED" if passed else "QUARANTINED",
            summary="Batch trust restored after verified repair artifact." if passed else "Batch remains quarantined.",
        )
    return VerificationResult(
        run_id=source_run_id,
        passed=False,
        finding_ids=proposal.evidence_refs,
        quarantine_state="QUARANTINED",
        summary="Action requires human review; incident is not marked resolved.",
    )
