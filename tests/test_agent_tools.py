"""CP-6 workflow-state, tool-boundary, approval and verification tests."""

import json

import pytest
from pydantic import ValidationError

from datagard.agent import AgentOrchestrator
from datagard.config import get_settings
from datagard.contracts import (
    ApprovalInput,
    IncidentActionInput,
    RepairInput,
    ToolRequest,
)
from datagard.ingestion import BASE_SCHEMA, generate_synthetic_dataset
from datagard.incidents import IncidentService
from datagard.metadata import LineageGraph
from datagard.quality import evaluate_quality
from datagard.rag import RunbookRetriever
from datagard.tools import ToolRegistry


def _workflow_for_scenario(scenario_id: str, settings=None):
    settings = settings or get_settings()
    dataset = generate_synthetic_dataset(settings)
    labels = {label.run_id: label for label in dataset.labels}
    run = next(item for item in dataset.runs if labels[item.run_id].scenario_id == scenario_id)
    findings = evaluate_quality(run, BASE_SCHEMA, settings.quality)
    incidents = IncidentService()
    incident = incidents.record_detection(
        run, findings, is_anomaly=True, detector_version="test-detector"
    )[0]
    retriever = RunbookRetriever(settings.retrieval, settings.resolved_runbooks_dir)
    tools = ToolRegistry(dataset.runs, incidents, retriever, settings)
    agent = AgentOrchestrator(settings, tools)
    lineage = LineageGraph()
    lineage.add_dependency("orders_daily", "orders_source")
    state = agent.investigate(
        incident,
        run,
        findings,
        BASE_SCHEMA,
        lineage,
        dataset.runs,
        f"{incident.incident_family} data quality investigation",
    )
    return settings, dataset, run, findings, incident, incidents, tools, agent, state


def test_quarantine_and_rerun_are_typed_audited_and_preserve_source() -> None:
    settings, dataset, run, findings, incident, incidents, tools, agent, state = _workflow_for_scenario("row_count_drop")
    assert state.current_status == "PROPOSED"
    assert state.rca_hypotheses
    assert state.retrieved_runbook_refs

    quarantine = next(item for item in state.action_proposals if item.tool_name == "quarantine_batch")
    state = agent.execute_action(quarantine.action_id)
    assert state.current_status == "PROPOSED"
    assert state.verification_result is not None and state.verification_result.passed
    original = next(item for item in dataset.runs if item.run_id == run.run_id)
    assert original == run
    assert tools.audit_events[-1].status == "SUCCEEDED"

    # A separate tool request retries the same idempotency key and does not duplicate state.
    repeated = tools.execute(
        ToolRequest(tool_name="quarantine_batch", payload=IncidentActionInput(
            incident_id=incident.incident_id, idempotency_key=quarantine.action_id
        )),
        "repeat-correlation",
    )
    assert repeated.status == "SUCCEEDED"
    inspection = tools.execute(
        ToolRequest(tool_name="inspect_pipeline", payload={"run_id": run.run_id}),
        "inspect-correlation",
    )
    assert inspection.data["batch_state"] == "QUARANTINED"
    assert len(tools.simulated_runs) == 0


def test_rerun_creates_separate_record_and_truthful_failed_verification() -> None:
    settings, dataset, run, _, _, _, _, agent, state = _workflow_for_scenario("row_count_drop")
    quarantine = next(item for item in state.action_proposals if item.tool_name == "quarantine_batch")
    state = agent.execute_action(quarantine.action_id)
    rerun = next(item for item in state.action_proposals if item.tool_name == "simulate_rerun")
    state = agent.execute_action(rerun.action_id)
    assert state.current_status == "ESCALATED"
    assert state.verification_result is not None
    assert not state.verification_result.passed
    assert state.verification_result.finding_ids
    assert state.verification_result.run_id != run.run_id
    assert next(item for item in dataset.runs if item.run_id == run.run_id) == run


def test_high_risk_schema_repair_cannot_bypass_approval(tmp_path) -> None:
    settings = get_settings().model_copy(update={
        "actions": get_settings().actions.model_copy(update={"artifact_dir": tmp_path})
    })
    settings, dataset, run, findings, incident, incidents, tools, agent, state = _workflow_for_scenario("schema_drift", settings)
    repair = next(item for item in state.action_proposals if item.tool_name == "simulate_repair")
    assert repair.requires_approval

    bypass = tools.execute(ToolRequest(
        tool_name="simulate_repair",
        payload=RepairInput(
            incident_id=incident.incident_id,
            idempotency_key="bypass",
            approval_id="missing",
            action_id=repair.action_id,
            repair_kind="align_schema",
        ),
    ), state.correlation_id)
    assert bypass.status == "REJECTED"
    assert not tools.simulated_runs

    quarantine = next(item for item in state.action_proposals if item.tool_name == "quarantine_batch")
    state = agent.execute_action(quarantine.action_id)
    assert state.current_status == "PROPOSED"

    state = agent.execute_action(repair.action_id)
    assert state.current_status == "AWAITING_APPROVAL"
    rejected_role = tools.execute(ToolRequest(
        tool_name="record_approval",
        payload=ApprovalInput(
            action_id=repair.action_id,
            decision="APPROVED",
            approver_role="viewer",
            reason="Wrong role test",
        ),
    ), state.correlation_id)
    assert rejected_role.status == "REJECTED"
    state = agent.record_approval("APPROVED", settings.actions.approval_role, "Schema owner approved the isolated simulation")
    assert state.approval_status == "APPROVED"
    state = agent.execute_action(repair.action_id)
    assert state.current_status == "PROPOSED"
    assert state.verification_result is not None and state.verification_result.passed
    assert run.observed_schema != BASE_SCHEMA
    assert next(item for item in dataset.runs if item.run_id == run.run_id).observed_schema == run.observed_schema
    artifact_files = list(tmp_path.glob("*.json"))
    assert len(artifact_files) == 1
    artifact = json.loads(artifact_files[0].read_text(encoding="utf-8"))
    assert artifact["original_run_id"] == run.run_id
    assert artifact["repaired_run"]["observed_schema"]
    assert any(event.status == "REJECTED" for event in tools.audit_events)
    release = next(item for item in state.action_proposals if item.tool_name == "release_batch")
    state = agent.execute_action(release.action_id)
    assert state.current_status == "RESOLVED"
    assert state.verification_result is not None and state.verification_result.quarantine_state == "TRUSTED"


def test_tool_schema_rejects_arbitrary_fields_and_invalid_transition() -> None:
    with pytest.raises(ValidationError):
        IncidentActionInput(incident_id="i", idempotency_key="k", filesystem_path="/tmp/x")
    with pytest.raises(RuntimeError):
        AgentOrchestrator(get_settings(), _workflow_for_scenario("row_count_drop")[6]).execute_action("unknown")
