"""Thin HTTP adapters that delegate all workflows to application services."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from datagard.application import ApplicationServices

router = APIRouter(prefix="/api/v1")


class InvestigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runbook_query: str | None = Field(default=None, max_length=500)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    approver_role: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=1000)


def _services(request: Request) -> ApplicationServices:
    return request.app.state.services


@router.post("/demo/generate")
def generate_demo(request: Request) -> dict[str, object]:
    return _services(request).generate_demo_data()


@router.get("/pipelines")
def list_pipelines(request: Request) -> tuple[dict[str, object], ...]:
    return _services(request).list_pipelines()


@router.get("/runs")
def list_runs(request: Request, limit: int = 100) -> tuple[object, ...]:
    try:
        return _services(request).list_runs(limit)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, object]:
    try:
        run, findings = _services(request).get_run(run_id)
        return {"run": run, "findings": findings}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/runs/{run_id}/analyze")
def analyze_run(run_id: str, request: Request) -> dict[str, object]:
    try:
        return _services(request).analyze_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/incidents")
def list_incidents(request: Request) -> tuple[object, ...]:
    return _services(request).list_incidents()


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, request: Request) -> dict[str, object]:
    try:
        incident, run, findings = _services(request).get_incident(incident_id)
        agent = _services(request).agents.get(incident_id)
        return {"incident": incident, "run": run, "findings": findings, "agent_state": agent.state if agent else None}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/incidents/{incident_id}/investigate")
def investigate(incident_id: str, body: InvestigateRequest, request: Request) -> object:
    try:
        return _services(request).investigate(incident_id, body.runbook_query)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, body: ApprovalRequest, request: Request) -> object:
    try:
        return _services(request).approve_action(action_id, body.decision, body.approver_role, body.reason)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/actions/{action_id}/execute")
def execute_action(action_id: str, request: Request) -> object:
    try:
        return _services(request).execute_action(action_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/incidents/{incident_id}/timeline")
def incident_timeline(incident_id: str, request: Request) -> tuple[dict[str, object], ...]:
    try:
        return _services(request).timeline(incident_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/evaluation/summary")
def evaluation_summary(request: Request) -> dict[str, object]:
    return _services(request).evaluation_summary()


@router.get("/dashboard/summary")
def dashboard_summary(request: Request) -> dict[str, object]:
    services = _services(request)
    runs = services.list_runs(limit=1000)
    incidents = services.list_incidents()
    return {
        "pipeline_count": len(services.list_pipelines()),
        "run_count": len(services.runs),
        "failed_run_count": sum(run.status == "FAILED" for run in runs),
        "incident_count": len(incidents),
        "open_incident_count": sum(item.status in {"OPEN", "INVESTIGATING"} for item in incidents),
        "latest_run_id": runs[0].run_id if runs else None,
    }


@router.get("/dip/artifacts")
def list_dip_artifacts(request: Request) -> tuple[dict[str, object], ...]:
    return _services(request).list_dip_artifacts()


@router.get("/dip/artifacts/{artifact_id}/images/{stage}")
def get_dip_image(
    artifact_id: str,
    stage: Literal[
        "raw", "validity", "ground_truth", "baseline", "improved",
        "baseline_overlay", "improved_overlay", "filtered", "adaptive",
    ],
    request: Request,
) -> FileResponse:
    try:
        image_path = _services(request).dip_image_path(artifact_id, stage)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return FileResponse(image_path)
