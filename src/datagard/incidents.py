"""Incident creation and stable-key deduplication."""

import logging
import re

from datagard.contracts import Incident, PipelineRun, QualityFinding

logger = logging.getLogger(__name__)


class IncidentService:
    """Create at most one in-memory incident per run and family."""

    def __init__(self) -> None:
        self._incidents: dict[tuple[str, str, str], Incident] = {}

    def record_detection(
        self,
        run: PipelineRun,
        findings: tuple[QualityFinding, ...],
        *,
        is_anomaly: bool,
        detector_version: str,
    ) -> tuple[Incident, ...]:
        """Group findings into incident families only when the detector flags a run."""

        if not is_anomaly:
            return ()
        grouped: dict[str, list[QualityFinding]] = {}
        for finding in findings:
            grouped.setdefault(_family_for_rule(finding.rule_id), []).append(finding)
        if not grouped:
            grouped["ANOMALY"] = []

        incidents: list[Incident] = []
        for family, family_findings in sorted(grouped.items()):
            key = (run.pipeline_id, run.run_id, family)
            existing = self._incidents.get(key)
            refs = tuple(sorted(item.finding_id for item in family_findings))
            if existing is not None:
                updated = existing.model_copy(update={"evidence_refs": tuple(sorted(set(existing.evidence_refs + refs)))})
                self._incidents[key] = updated
                incidents.append(updated)
                continue
            severity = max((item.severity for item in family_findings), key=_severity_rank, default="MEDIUM")
            incident = Incident(
                incident_id=_incident_id(run.pipeline_id, run.run_id, family),
                pipeline_id=run.pipeline_id,
                affected_run_id=run.run_id,
                incident_family=family,
                severity=severity,
                status="OPEN",
                detected_at=run.started_at,
                evidence_refs=refs,
                detector_version=detector_version,
            )
            self._incidents[key] = incident
            incidents.append(incident)
        logger.info("incident detection recorded", extra={"run_id": run.run_id, "incident_count": len(incidents)})
        return tuple(incidents)

    def list_incidents(self) -> tuple[Incident, ...]:
        """Return incidents in detection order."""

        return tuple(sorted(self._incidents.values(), key=lambda incident: (incident.detected_at, incident.incident_id)))

    def get(self, incident_id: str) -> Incident | None:
        """Load one incident by stable identifier."""

        return next((item for item in self._incidents.values() if item.incident_id == incident_id), None)

    def restore(self, incidents: tuple[Incident, ...]) -> None:
        """Restore persisted incidents when the application starts."""

        for incident in incidents:
            key = (incident.pipeline_id, incident.affected_run_id, incident.incident_family)
            self._incidents[key] = incident

    def set_status(self, incident_id: str, status: str) -> Incident:
        """Apply a valid incident lifecycle transition in the incident owner."""

        current = self.get(incident_id)
        if current is None:
            raise ValueError("Incident does not exist")
        allowed = {
            "OPEN": {"INVESTIGATING", "RESOLVED", "ESCALATED"},
            "INVESTIGATING": {"OPEN", "RESOLVED", "ESCALATED"},
            "ESCALATED": {"INVESTIGATING", "RESOLVED"},
            "RESOLVED": set(),
        }
        if status not in allowed[current.status]:
            raise ValueError(f"Invalid incident transition: {current.status} -> {status}")
        updated = current.model_copy(update={"status": status})
        self._incidents[(current.pipeline_id, current.affected_run_id, current.incident_family)] = updated
        return updated


def _family_for_rule(rule_id: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", rule_id.upper()).strip("_")
    if normalized.startswith("SCHEMA_"):
        return "SCHEMA_DRIFT"
    if normalized.startswith("NULL_"):
        return "NULL_SURGE"
    if normalized.startswith("DUPLICATE_"):
        return "DUPLICATE_SPIKE"
    if normalized.startswith("ROW_COUNT_"):
        return "ROW_COUNT_DROP"
    if normalized.startswith("DISTRIBUTION_") or normalized == "INVALID_RANGE":
        return "DISTRIBUTION_SHIFT"
    if normalized in {"PIPELINE_FAILED", "RUNTIME_SPIKE"}:
        return "EXECUTION_FAILURE"
    return normalized


def _severity_rank(severity: str) -> int:
    return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}[severity]


def _incident_id(pipeline_id: str, run_id: str, family: str) -> str:
    return f"{pipeline_id}:{run_id}:{family}"
