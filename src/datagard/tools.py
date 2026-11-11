"""Registered typed tools are the only route to local state-changing actions."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel

from datagard.config import Settings
from datagard.contracts import (
    ApprovalInput,
    ApprovalRecord,
    EscalateInput,
    IncidentActionInput,
    InspectPipelineInput,
    PipelineRun,
    RepairInput,
    ReleaseBatchInput,
    RetrieveRunbookInput,
    RerunInput,
    ToolAuditEvent,
    ToolRequest,
    ToolResult,
)
from datagard.ingestion import BASE_SCHEMA
from datagard.incidents import IncidentService
from datagard.quality import evaluate_quality
from datagard.rag import RunbookRetriever

logger = logging.getLogger(__name__)

ToolPayload: TypeAlias = (
    InspectPipelineInput | RetrieveRunbookInput | IncidentActionInput | RerunInput |
    RepairInput | EscalateInput | ApprovalInput
    | ReleaseBatchInput
)


class ToolRegistry:
    """Allowlisted local tool boundary with preconditions, audit, and idempotency."""

    def __init__(
        self,
        runs: tuple[PipelineRun, ...],
        incidents: IncidentService,
        retriever: RunbookRetriever,
        settings: Settings,
        stored_state: dict[str, object] | None = None,
    ) -> None:
        self._runs = {run.run_id: run for run in runs}
        self._incidents = incidents
        self._retriever = retriever
        self._settings = settings
        self._batch_states: dict[str, str] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
        self._escalations: list[dict[str, object]] = []
        self._idempotent_results: dict[tuple[str, str], ToolResult] = {}
        self._audit_events: list[ToolAuditEvent] = []
        self._simulated_runs: dict[str, PipelineRun] = {}
        self._verified_run_incidents: dict[str, str] = {}
        if stored_state:
            self._restore_state(stored_state)

    @property
    def audit_events(self) -> tuple[ToolAuditEvent, ...]:
        return tuple(self._audit_events)

    @property
    def simulated_runs(self) -> tuple[PipelineRun, ...]:
        return tuple(self._simulated_runs.values())

    @property
    def approvals(self) -> tuple[ApprovalRecord, ...]:
        return tuple(self._approvals.values())

    def approval_for_action(self, action_id: str) -> ApprovalRecord | None:
        return next((item for item in self._approvals.values() if item.action_id == action_id), None)

    def export_state(self) -> dict[str, object]:
        """Return JSON-compatible local tool state for persistence."""

        return {
            "batch_states": self._batch_states,
            "approvals": [item.model_dump(mode="json") for item in self._approvals.values()],
            "escalations": self._escalations,
            "idempotent_results": [
                {"tool_name": name, "idempotency_key": key, "result": value.model_dump(mode="json")}
                for (name, key), value in self._idempotent_results.items()
            ],
            "audit_events": [item.model_dump(mode="json") for item in self._audit_events],
            "simulated_runs": [item.model_dump(mode="json") for item in self._simulated_runs.values()],
            "verified_run_incidents": self._verified_run_incidents,
        }

    def describe_tools(self) -> tuple[dict[str, object], ...]:
        """Expose the registered names, schemas, risks, and side-effect boundaries."""

        return tuple(
            _tool_description(name, schema, risk, effect, preconditions, idempotent, failures)
            for name, schema, risk, effect, preconditions, idempotent, failures in (
                ("inspect_pipeline", InspectPipelineInput, "READ_ONLY", "Read run and incident context", ("run exists",), True, ("unknown run",)),
                ("retrieve_runbook", RetrieveRunbookInput, "READ_ONLY", "Read curated local runbook sections", ("query is non-empty",), True, ("empty corpus",)),
                ("quarantine_batch", IncidentActionInput, "LOW", "Set local batch trust state", ("incident is open", "run exists"), True, ("unknown/closed incident",)),
                ("release_batch", ReleaseBatchInput, "LOW", "Restore trust only after verified output", ("batch is quarantined", "verification belongs to incident and passed"), True, ("missing/failed verification",)),
                ("simulate_rerun", RerunInput, "LOW", "Create separate local run record; no scheduler call", ("incident is open", "run exists"), True, ("unknown/closed incident",)),
                ("simulate_repair", RepairInput, "HIGH", "Write isolated schema-alignment artifact", ("incident is open", "exact action has configured-role approval"), True, ("missing/rejected approval", "failed quality verification")),
                ("escalate_incident", EscalateInput, "LOW", "Add simulated human-review request", ("incident is open", "reason supplied"), True, ("unknown/closed incident",)),
                ("record_approval", ApprovalInput, "AUDIT", "Record explicit simulated reviewer decision", ("role matches configured approval role",), False, ("unauthorized role",)),
            )
        )

    def execute(self, request: ToolRequest, correlation_id: str) -> ToolResult:
        """Validate the tool/payload pairing, execute one allowlisted operation, and audit it."""

        now = datetime.now(timezone.utc)
        idempotency_key = _payload_idempotency_key(request.payload)
        try:
            cached = self._idempotent_results.get((request.tool_name, idempotency_key))
            if cached is not None:
                result = cached
            else:
                data = self._dispatch(request.tool_name, request.payload)
                result = ToolResult(tool_name=request.tool_name, status="SUCCEEDED", data=data)
                if idempotency_key:
                    self._idempotent_results[(request.tool_name, idempotency_key)] = result
            incident_id = _payload_incident_id(request.payload)
            self._audit_events.append(ToolAuditEvent(
                event_id=_stable_id("evt", f"{correlation_id}:{len(self._audit_events)}"),
                correlation_id=correlation_id,
                incident_id=incident_id,
                tool_name=request.tool_name,
                idempotency_key=idempotency_key or "read-only",
                status=result.status,
                detail="Allowlisted tool completed." if result.status == "SUCCEEDED" else str(result.data.get("reason", "Rejected")),
                occurred_at=now,
            ))
            return result
        except (KeyError, ValueError, PermissionError, TypeError) as error:
            incident_id = _payload_incident_id(request.payload)
            self._audit_events.append(ToolAuditEvent(
                event_id=_stable_id("evt", f"{correlation_id}:{len(self._audit_events)}"),
                correlation_id=correlation_id,
                incident_id=incident_id,
                tool_name=request.tool_name,
                idempotency_key=idempotency_key or "read-only",
                status="REJECTED",
                detail=str(error),
                occurred_at=now,
            ))
            logger.warning("tool invocation rejected", extra={"tool_name": request.tool_name, "reason": str(error)})
            return ToolResult(tool_name=request.tool_name, status="REJECTED", data={"reason": str(error)})

    def _dispatch(self, tool_name: str, payload: ToolPayload) -> dict[str, object]:
        if tool_name == "inspect_pipeline" and isinstance(payload, InspectPipelineInput):
            return self._inspect(payload)
        if tool_name == "retrieve_runbook" and isinstance(payload, RetrieveRunbookInput):
            chunks = self._retriever.retrieve(payload.query)
            return {"chunks": [chunk.model_dump(mode="json") for chunk in chunks]}
        if tool_name == "quarantine_batch" and isinstance(payload, IncidentActionInput):
            incident = self._require_open_incident(payload.incident_id)
            run = self._require_run(incident.affected_run_id)
            self._batch_states[run.run_id] = "QUARANTINED"
            return {"run_id": run.run_id, "batch_state": "QUARANTINED", "original_preserved": True}
        if tool_name == "release_batch" and isinstance(payload, ReleaseBatchInput):
            incident = self._require_open_incident(payload.incident_id)
            run = self._require_run(incident.affected_run_id)
            if self._batch_states.get(run.run_id) != "QUARANTINED":
                raise ValueError("Batch is not quarantined")
            if self._verified_run_incidents.get(payload.verification_run_id) != incident.incident_id:
                raise PermissionError("A passing post-action verification for this incident is required")
            self._batch_states[run.run_id] = "TRUSTED"
            return {"run_id": run.run_id, "batch_state": "TRUSTED", "verification_run_id": payload.verification_run_id}
        if tool_name == "simulate_rerun" and isinstance(payload, RerunInput):
            incident = self._require_open_incident(payload.incident_id)
            original = self._require_run(incident.affected_run_id)
            run_id = _stable_id("simrun", f"{original.run_id}:{payload.idempotency_key}")
            simulated = original.model_copy(update={
                "run_id": run_id,
                "started_at": original.completed_at + timedelta(seconds=1),
                "completed_at": original.completed_at + timedelta(seconds=1, milliseconds=original.duration_ms),
            })
            self._simulated_runs.setdefault(run_id, simulated)
            findings = evaluate_quality(simulated, BASE_SCHEMA, self._settings.quality)
            if not findings:
                self._verified_run_incidents[run_id] = incident.incident_id
            return {
                "original_run_id": original.run_id,
                "simulated_run": simulated.model_dump(mode="json"),
                "finding_ids": [finding.finding_id for finding in findings],
                "verified": not findings,
                "original_preserved": original.run_id in self._runs,
            }
        if tool_name == "simulate_repair" and isinstance(payload, RepairInput):
            return self._simulate_repair(payload)
        if tool_name == "escalate_incident" and isinstance(payload, EscalateInput):
            incident = self._require_open_incident(payload.incident_id)
            escalation = {
                "incident_id": incident.incident_id,
                "queue": "simulated-data-engineering-review",
                "reason": payload.reason,
                "evidence_refs": payload.evidence_refs,
            }
            self._escalations.append(escalation)
            return escalation
        if tool_name == "record_approval" and isinstance(payload, ApprovalInput):
            if payload.approver_role != self._settings.actions.approval_role:
                raise PermissionError("Approver role does not satisfy configured action policy")
            approval = ApprovalRecord(
                approval_id=_stable_id("approval", f"{payload.action_id}:{payload.approver_role}:{payload.decision}"),
                action_id=payload.action_id,
                decision=payload.decision,
                approver_role=payload.approver_role,
                reason=payload.reason,
                decided_at=datetime.now(timezone.utc),
            )
            self._approvals[approval.approval_id] = approval
            return approval.model_dump(mode="json")
        raise ValueError("Tool name and validated input schema do not match a registered tool")

    def _restore_state(self, state: dict[str, object]) -> None:
        self._batch_states.update(state.get("batch_states", {}))
        self._approvals.update({item.approval_id: item for item in (
            ApprovalRecord.model_validate(raw) for raw in state.get("approvals", [])
        )})
        self._escalations.extend(state.get("escalations", []))
        self._idempotent_results.update({
            (raw["tool_name"], raw["idempotency_key"]): ToolResult.model_validate(raw["result"])
            for raw in state.get("idempotent_results", [])
        })
        self._audit_events.extend(ToolAuditEvent.model_validate(raw) for raw in state.get("audit_events", []))
        self._simulated_runs.update({
            run.run_id: run for run in (PipelineRun.model_validate(raw) for raw in state.get("simulated_runs", []))
        })
        self._verified_run_incidents.update(state.get("verified_run_incidents", {}))

    def _simulate_repair(self, payload: RepairInput) -> dict[str, object]:
        incident = self._require_open_incident(payload.incident_id)
        approval = self._approvals.get(payload.approval_id)
        if approval is None or approval.action_id != payload.action_id:
            raise PermissionError("An approval for this exact action is required")
        if approval.decision != "APPROVED":
            raise PermissionError("The action was not approved")
        original = self._require_run(incident.affected_run_id)
        repaired = original.model_copy(update={"run_id": _stable_id("repair", payload.action_id), "schema_version": "v1", "observed_schema": BASE_SCHEMA})
        findings = evaluate_quality(repaired, BASE_SCHEMA, self._settings.quality)
        if any(finding.rule_id.startswith("SCHEMA_") for finding in findings):
            raise ValueError("Schema alignment did not pass post-action verification")
        if not findings:
            self._simulated_runs.setdefault(repaired.run_id, repaired)
            self._verified_run_incidents[repaired.run_id] = incident.incident_id
        output_dir = self._settings.resolved_action_artifact_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / f"{repaired.run_id}.json"
        artifact_path.write_text(json.dumps({
            "action_id": payload.action_id,
            "repair_kind": payload.repair_kind,
            "original_run_id": original.run_id,
            "repaired_run": repaired.model_dump(mode="json"),
            "remaining_finding_ids": [finding.finding_id for finding in findings],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "original_run_id": original.run_id,
            "repaired_run": repaired.model_dump(mode="json"),
            "artifact_ref": str(artifact_path.relative_to(self._settings.resolved_action_artifact_dir.parent)),
            "schema_verified": True,
            "quality_verified": not findings,
            "remaining_finding_ids": [finding.finding_id for finding in findings],
            "original_preserved": original.run_id in self._runs,
        }

    def _inspect(self, payload: InspectPipelineInput) -> dict[str, object]:
        run = self._require_run(payload.run_id)
        incidents = tuple(item for item in self._incidents.list_incidents() if item.affected_run_id == run.run_id)
        return {
            "run": run.model_dump(mode="json"),
            "batch_state": self._batch_states.get(run.run_id, "TRUSTED"),
            "incidents": [item.model_dump(mode="json") for item in incidents],
        }

    def _require_run(self, run_id: str) -> PipelineRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise ValueError("Run does not exist in the local dataset") from error

    def _require_open_incident(self, incident_id: str):
        incident = next((item for item in self._incidents.list_incidents() if item.incident_id == incident_id), None)
        if incident is None or incident.status not in {"OPEN", "INVESTIGATING"}:
            raise ValueError("Incident must exist and be open or under investigation")
        return incident


def _tool_description(
    name: str,
    schema: type[BaseModel],
    risk: str,
    side_effect: str,
    preconditions: tuple[str, ...],
    idempotent: bool,
    failures: tuple[str, ...],
) -> dict[str, object]:
    return {
        "name": name,
        "input_schema": schema.model_json_schema(),
        "output_schema": ToolResult.model_json_schema(),
        "risk": risk,
        "preconditions": preconditions,
        "idempotent": idempotent,
        "allowed_side_effect": side_effect,
        "failure_modes": failures,
    }


def _payload_incident_id(payload: ToolPayload) -> str:
    return getattr(payload, "incident_id", None) or ""


def _payload_idempotency_key(payload: ToolPayload) -> str:
    return getattr(payload, "idempotency_key", "")


def _stable_id(prefix: str, source: str) -> str:
    return f"{prefix}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"
