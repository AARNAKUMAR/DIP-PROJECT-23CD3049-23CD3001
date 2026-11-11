"""CP-7 SQLite restart and thin API integration coverage."""

from fastapi.testclient import TestClient

from datagard.config import get_settings
from datagard.ingestion import generate_synthetic_dataset
from datagard.main import create_app
from datagard.persistence import SQLiteStore


def _isolated_settings(tmp_path):
    settings = get_settings()
    return settings.model_copy(update={
        "persistence": settings.persistence.model_copy(update={"database_path": tmp_path / "prototype.sqlite3"}),
        "data_output_dir": tmp_path / "data",
        "actions": settings.actions.model_copy(update={"artifact_dir": tmp_path / "actions"}),
    })


def test_sqlite_store_round_trips_and_rejects_unknown_entity(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "store.sqlite3")
    store.put("artifacts", "artifact-1", {"path": "artifacts/fingerprints/example.png"})
    reopened = SQLiteStore(tmp_path / "store.sqlite3")

    assert reopened.get("artifacts", "artifact-1") == {"path": "artifacts/fingerprints/example.png"}
    assert reopened.list("artifacts") == ({"path": "artifacts/fingerprints/example.png"},)
    assert reopened.delete("artifacts", "artifact-1")
    assert reopened.get("artifacts", "artifact-1") is None


def test_api_closed_loop_and_domain_state_survive_application_restart(tmp_path) -> None:
    settings = _isolated_settings(tmp_path)
    dataset = generate_synthetic_dataset(settings)
    run = next(
        item for item, label in zip(dataset.runs, dataset.labels, strict=True)
        if label.scenario_id == "row_count_drop"
    )
    app = create_app(settings)
    with TestClient(app) as client:
        summary = client.get("/api/v1/dashboard/summary")
        assert summary.status_code == 200
        assert summary.json()["run_count"] == 360
        analysis = client.post(f"/api/v1/runs/{run.run_id}/analyze")
        assert analysis.status_code == 200
        incident_id = analysis.json()["incidents"][0]["incident_id"]
        investigation = client.post(
            f"/api/v1/incidents/{incident_id}/investigate",
            json={"runbook_query": "row count drop upstream volume rerun"},
        )
        assert investigation.status_code == 200
        state = investigation.json()
        assert state["current_status"] == "PROPOSED"
        assert state["rca_hypotheses"][0]["supporting_evidence_ids"]

        quarantine = next(item for item in state["action_proposals"] if item["tool_name"] == "quarantine_batch")
        response = client.post(f"/api/v1/actions/{quarantine['action_id']}/execute")
        assert response.status_code == 200
        assert response.json()["current_status"] == "PROPOSED"

        rerun = next(item for item in state["action_proposals"] if item["tool_name"] == "simulate_rerun")
        response = client.post(f"/api/v1/actions/{rerun['action_id']}/execute")
        assert response.status_code == 200
        assert response.json()["current_status"] == "ESCALATED"
        timeline = client.get(f"/api/v1/incidents/{incident_id}/timeline")
        assert timeline.status_code == 200
        assert any(item["kind"] == "tool" for item in timeline.json())

    restarted_app = create_app(settings)
    with TestClient(restarted_app) as client:
        restored_run = client.get(f"/api/v1/runs/{run.run_id}")
        restored_incident = client.get(f"/api/v1/incidents/{incident_id}")
        restored_timeline = client.get(f"/api/v1/incidents/{incident_id}/timeline")
        assert restored_run.status_code == 200
        assert restored_incident.status_code == 200
        assert restored_incident.json()["incident"]["status"] == "ESCALATED"
        assert restored_incident.json()["agent_state"]["current_status"] == "ESCALATED"
        assert len(restored_timeline.json()) >= len(timeline.json())


def test_pending_high_risk_approval_survives_restart_and_completes(tmp_path) -> None:
    settings = _isolated_settings(tmp_path)
    dataset = generate_synthetic_dataset(settings)
    run = next(
        item for item, label in zip(dataset.runs, dataset.labels, strict=True)
        if label.scenario_id == "schema_drift"
    )
    with TestClient(create_app(settings)) as client:
        analysis = client.post(f"/api/v1/runs/{run.run_id}/analyze")
        incident_id = analysis.json()["incidents"][0]["incident_id"]
        state = client.post(f"/api/v1/incidents/{incident_id}/investigate", json={}).json()
        quarantine = next(item for item in state["action_proposals"] if item["tool_name"] == "quarantine_batch")
        client.post(f"/api/v1/actions/{quarantine['action_id']}/execute")
        repair = next(item for item in state["action_proposals"] if item["tool_name"] == "simulate_repair")
        waiting = client.post(f"/api/v1/actions/{repair['action_id']}/execute").json()
        assert waiting["current_status"] == "AWAITING_APPROVAL"
        approved = client.post(
            f"/api/v1/actions/{repair['action_id']}/approve",
            json={
                "decision": "APPROVED",
                "approver_role": settings.actions.approval_role,
                "reason": "Reviewed schema compatibility for isolated simulation",
            },
        )
        assert approved.status_code == 200

    with TestClient(create_app(settings)) as client:
        restored = client.get(f"/api/v1/incidents/{incident_id}").json()["agent_state"]
        assert restored["current_status"] == "AWAITING_APPROVAL"
        assert restored["approval_status"] == "APPROVED"
        repair_result = client.post(f"/api/v1/actions/{repair['action_id']}/execute")
        assert repair_result.status_code == 200
        assert repair_result.json()["current_status"] == "PROPOSED"
        release = next(
            item for item in repair_result.json()["action_proposals"]
            if item["tool_name"] == "release_batch"
        )
        complete = client.post(f"/api/v1/actions/{release['action_id']}/execute")
        assert complete.status_code == 200
        assert complete.json()["current_status"] == "RESOLVED"


def test_dip_api_lists_manifests_and_only_serves_allowlisted_images(tmp_path) -> None:
    settings = _isolated_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        artifacts = client.get("/api/v1/dip/artifacts")
        assert artifacts.status_code == 200
        assert artifacts.json()
        artifact_id = artifacts.json()[0]["artifact_id"]
        image = client.get(f"/api/v1/dip/artifacts/{artifact_id}/images/raw")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        invalid_stage = client.get(f"/api/v1/dip/artifacts/{artifact_id}/images/../../secrets")
        assert invalid_stage.status_code in {404, 422}
