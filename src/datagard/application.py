"""Application use cases shared by FastAPI and the Streamlit API client."""

import json
import logging
from pathlib import Path

from datagard.agent import AgentOrchestrator
from datagard.config import Settings
from datagard.contracts import (
    AgentState,
    AgentTransition,
    ApprovalRecord,
    Incident,
    PipelineRun,
    QualityFinding,
    ScenarioTruth,
    ToolAuditEvent,
)
from datagard.detection import rule_baseline_is_anomaly
from datagard.ingestion import BASE_SCHEMA, generate_synthetic_dataset, write_synthetic_dataset
from datagard.incidents import IncidentService
from datagard.metadata import LineageGraph
from datagard.persistence import SQLiteStore
from datagard.quality import evaluate_quality
from datagard.rag import RunbookRetriever
from datagard.tools import ToolRegistry

logger = logging.getLogger(__name__)


class ApplicationServices:
    """Compose domain services, preserving one owner per workflow concern."""

    def __init__(self, settings: Settings, store: SQLiteStore | None = None) -> None:
        self.settings = settings
        self.store = store or SQLiteStore(settings.resolved_database_path)
        generated = generate_synthetic_dataset(settings)
        stored_runs = tuple(PipelineRun.model_validate(item) for item in self.store.list("runs"))
        self.runs: dict[str, PipelineRun] = {run.run_id: run for run in (stored_runs or generated.runs)}
        if not stored_runs:
            for run in self.runs.values():
                self.store.put("runs", run.run_id, run)
        persisted_incidents = tuple(Incident.model_validate(item) for item in self.store.list("incidents"))
        self.incidents = IncidentService()
        self.incidents.restore(persisted_incidents)
        self.findings: dict[str, tuple[QualityFinding, ...]] = {
            run_id: tuple(QualityFinding.model_validate(finding) for finding in records)
            for run_id, records in _load_findings(self.store).items()
        }
        self.retriever = RunbookRetriever(settings.retrieval, settings.resolved_runbooks_dir)
        tool_snapshot = self.store.get("tool_states", "primary")
        self.tools = ToolRegistry(
            tuple(self.runs.values()), self.incidents, self.retriever, settings, tool_snapshot
        )
        self.agents: dict[str, AgentOrchestrator] = {}
        self._restore_agents()
        if not stored_runs:
            write_synthetic_dataset(generated, settings.resolved_data_output_dir)

    def generate_demo_data(self) -> dict[str, object]:
        dataset = generate_synthetic_dataset(self.settings)
        self.runs = {run.run_id: run for run in dataset.runs}
        for run in dataset.runs:
            self.store.put("runs", run.run_id, run)
        write_synthetic_dataset(dataset, self.settings.resolved_data_output_dir)
        logger.info("demo data generated and persisted", extra={"run_count": len(dataset.runs)})
        return {"run_count": len(dataset.runs), "scenario_count": len({truth.scenario_id for truth in dataset.labels})}

    def list_pipelines(self) -> tuple[dict[str, object], ...]:
        grouped: dict[str, list[PipelineRun]] = {}
        for run in self.runs.values():
            grouped.setdefault(run.pipeline_id, []).append(run)
        return tuple({
            "pipeline_id": pipeline_id,
            "run_count": len(runs),
            "latest_run_id": max(runs, key=lambda item: item.started_at).run_id,
            "failed_run_count": sum(run.status == "FAILED" for run in runs),
        } for pipeline_id, runs in sorted(grouped.items()))

    def list_runs(self, limit: int = 100) -> tuple[PipelineRun, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        return tuple(sorted(self.runs.values(), key=lambda run: run.started_at, reverse=True)[:limit])

    def get_run(self, run_id: str) -> tuple[PipelineRun, tuple[QualityFinding, ...]]:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run ID: {run_id}")
        findings = self.findings.get(run_id)
        if findings is None:
            findings = evaluate_quality(run, BASE_SCHEMA, self.settings.quality)
            self._save_findings(run_id, findings)
        return run, findings

    def analyze_run(self, run_id: str) -> dict[str, object]:
        run, findings = self.get_run(run_id)
        is_anomaly = rule_baseline_is_anomaly(findings, self.settings.detection.baseline_severities)
        incidents = self.incidents.record_detection(
            run,
            findings,
            is_anomaly=is_anomaly,
            detector_version="severity-rule-baseline-1",
        )
        prediction = {
            "run_id": run.run_id,
            "anomaly_score": 1.0 if is_anomaly else 0.0,
            "is_anomaly": is_anomaly,
            "model_version": "severity-rule-baseline-1",
            "threshold": 0.5,
            "evidence_refs": tuple(finding.finding_id for finding in findings),
        }
        for incident in incidents:
            self.store.put("incidents", incident.incident_id, incident)
        return {"run": run, "findings": findings, "prediction": prediction, "incidents": incidents}

    def list_incidents(self) -> tuple[Incident, ...]:
        return self.incidents.list_incidents()

    def get_incident(self, incident_id: str) -> tuple[Incident, PipelineRun, tuple[QualityFinding, ...]]:
        incident = self.incidents.get(incident_id)
        if incident is None:
            raise KeyError(f"Unknown incident ID: {incident_id}")
        run, findings = self.get_run(incident.affected_run_id)
        return incident, run, findings

    def investigate(self, incident_id: str, runbook_query: str | None = None) -> AgentState:
        incident, run, findings = self.get_incident(incident_id)
        if incident.status == "OPEN":
            incident = self.incidents.set_status(incident_id, "INVESTIGATING")
            self.store.put("incidents", incident_id, incident)
        agent = self.agents.get(incident_id)
        if agent is None:
            agent = AgentOrchestrator(self.settings, self.tools)
            lineage = LineageGraph()
            lineage.add_dependency(run.pipeline_id, run.source_id)
            self.agents[incident_id] = agent
            state = agent.investigate(
                incident,
                run,
                findings,
                BASE_SCHEMA,
                lineage,
                tuple(self.runs.values()),
                runbook_query or f"{incident.incident_family} data quality response",
            )
        else:
            state = agent.state
        self._persist_agent(incident_id, agent)
        self._persist_tool_state()
        self._sync_incident_status(incident_id, state)
        return state

    def execute_action(self, action_id: str) -> AgentState:
        incident_id, agent = self._agent_for_action(action_id)
        state = agent.execute_action(action_id)
        self._persist_agent(incident_id, agent)
        self._persist_tool_state()
        self._sync_incident_status(incident_id, state)
        return state

    def approve_action(self, action_id: str, decision: str, role: str, reason: str) -> AgentState:
        incident_id, agent = self._agent_for_action(action_id)
        state = agent.record_approval(decision, role, reason)
        self._persist_agent(incident_id, agent)
        self._persist_tool_state()
        self._sync_incident_status(incident_id, state)
        return state

    def timeline(self, incident_id: str) -> tuple[dict[str, object], ...]:
        self.get_incident(incident_id)
        events: list[dict[str, object]] = []
        for raw in self.store.list("state_transitions"):
            if raw.get("incident_id") == incident_id:
                events.append({"kind": "state_transition", **raw})
        for event in self.tools.audit_events:
            if event.incident_id == incident_id:
                events.append({"kind": "tool", **event.model_dump(mode="json")})
        for approval in self.tools.approvals:
            agent = self.agents.get(incident_id)
            if agent and any(item.action_id == approval.action_id for item in agent.state.action_proposals):
                events.append({"kind": "approval", **approval.model_dump(mode="json")})
        return tuple(sorted(events, key=lambda item: str(item.get("occurred_at", item.get("decided_at", "")))))

    def evaluation_summary(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, relative_path in (
            ("detection", self.settings.evaluation.output_dir / "detection_metrics.json"),
            ("dip", self.settings.dip.evaluation_dir / "dip_metrics.json"),
        ):
            path = _resolve_path(relative_path)
            if path.exists():
                result[key] = json.loads(path.read_text(encoding="utf-8"))
        return result

    def list_dip_artifacts(self) -> tuple[dict[str, object], ...]:
        """List saved DQF manifests and register their provenance in SQLite."""

        root = self.settings.resolved_dip_artifact_dir.resolve()
        results: list[dict[str, object]] = []
        if not root.exists():
            return ()
        for path in sorted(root.glob("window_*/manifest.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(manifest.get("artifact_id"), str):
                continue
            summary = {
                "artifact_id": manifest["artifact_id"],
                "window_run_ids": manifest.get("window_run_ids", []),
                "channel_map": manifest.get("channel_map", []),
                "run_map": manifest.get("run_map", []),
                "encoder_version": manifest.get("encoder_version"),
                "baseline_version": manifest.get("baseline_version"),
                "manifest_ref": str(path.relative_to(root)),
            }
            self.store.put("artifacts", str(manifest["artifact_id"]), summary)
            results.append(summary)
        return tuple(results)

    def dip_image_path(self, artifact_id: str, stage: str) -> Path:
        """Resolve one known manifest and allowlisted image stage beneath artifact root."""

        path_keys = {
            "raw": "raw_image_path",
            "validity": "validity_mask_path",
            "ground_truth": "ground_truth_mask_path",
            "baseline": "baseline_mask_path",
            "improved": "improved_mask_path",
            "baseline_overlay": "baseline_overlay_path",
            "improved_overlay": "improved_overlay_path",
            "filtered": "filtered_image_path",
            "adaptive": "adaptive_mask_path",
        }
        if stage not in path_keys:
            raise KeyError(f"Unknown DQF image stage: {stage}")
        root = self.settings.resolved_dip_artifact_dir.resolve()
        for path in root.glob("window_*/manifest.json"):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("artifact_id") != artifact_id:
                continue
            image_path = Path(str(manifest[path_keys[stage]])).resolve()
            if not image_path.is_relative_to(root) or not image_path.is_file():
                raise ValueError("Manifest image reference is outside the configured artifact store or missing")
            return image_path
        raise KeyError(f"Unknown DQF artifact ID: {artifact_id}")

    def _save_findings(self, run_id: str, findings: tuple[QualityFinding, ...]) -> None:
        self.findings[run_id] = findings
        self.store.put("findings", run_id, {"run_id": run_id, "items": [item.model_dump(mode="json") for item in findings]})

    def _persist_agent(self, incident_id: str, agent: AgentOrchestrator) -> None:
        snapshot = agent.export_state()
        self.store.put("agent_states", incident_id, snapshot["state"])
        for index, transition in enumerate(snapshot["transitions"]):
            self.store.put("state_transitions", f"{incident_id}:{index:04d}", transition)
        state = agent.state
        for proposal in state.action_proposals:
            self.store.put("action_proposals", proposal.action_id, proposal)
        if state.verification_result is not None:
            self.store.put("outcomes", incident_id, state.verification_result)

    def _persist_tool_state(self) -> None:
        snapshot = self.tools.export_state()
        self.store.put("tool_states", "primary", snapshot)
        for approval in self.tools.approvals:
            self.store.put("approvals", approval.approval_id, approval)
        for event in self.tools.audit_events:
            self.store.put("tool_audit_events", event.event_id, event)
        for run in self.tools.simulated_runs:
            self.store.put("simulated_runs", run.run_id, run)

    def _restore_agents(self) -> None:
        transition_records: dict[str, list[AgentTransition]] = {}
        for record in self.store.list("state_transitions"):
            transition = AgentTransition.model_validate(record)
            transition_records.setdefault(transition.incident_id, []).append(transition)
        for raw in self.store.list("agent_states"):
            state = AgentState.model_validate(raw)
            agent = AgentOrchestrator(self.settings, self.tools)
            agent.restore(state, tuple(transition_records.get(state.incident_id, [])))
            self.agents[state.incident_id] = agent

    def _agent_for_action(self, action_id: str) -> tuple[str, AgentOrchestrator]:
        for incident_id, agent in self.agents.items():
            if any(proposal.action_id == action_id for proposal in agent.state.action_proposals):
                return incident_id, agent
        raise KeyError(f"Unknown action ID: {action_id}")

    def _sync_incident_status(self, incident_id: str, state: AgentState) -> None:
        incident = self.incidents.get(incident_id)
        if incident is None:
            return
        target = "RESOLVED" if state.current_status == "RESOLVED" else "ESCALATED" if state.current_status == "ESCALATED" else None
        if target and incident.status in {"OPEN", "INVESTIGATING"}:
            updated = self.incidents.set_status(incident_id, target)
            self.store.put("incidents", incident_id, updated)


def _load_findings(store: SQLiteStore) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for record in store.list("findings"):
        result[str(record["run_id"])] = list(record.get("items", []))
    return result


def _resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    from datagard.config import PROJECT_ROOT

    return PROJECT_ROOT / path
