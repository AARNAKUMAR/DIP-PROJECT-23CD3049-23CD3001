"""Streamlit API client for the DataGuard AI local prototype."""

import json
import os
import urllib.error
import urllib.request

import streamlit as st

from datagard.config import get_settings


settings = get_settings()
API_BASE_URL = os.environ.get("DATAGUARD_DASHBOARD_API_URL", settings.dashboard_api_base_url).rstrip("/")

st.set_page_config(page_title="DataGuard AI", page_icon="🛡️", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; max-width: 1440px;}
      [data-testid="stMetric"] {background:#f3f6fa; border:1px solid #e3e9f1; padding:14px; border-radius:10px;}
      .dg-subtle {color:#68778b; font-size:.92rem;}
      .dg-badge {display:inline-block; background:#fff4d6; color:#795600; padding:3px 9px; border-radius:99px; font-size:.8rem; font-weight:600;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api_json(path: str, method: str = "GET", body: dict[str, object] | None = None) -> object:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"API request failed for {path}: {error}") from error


def api_image(path: str) -> bytes:
    try:
        with urllib.request.urlopen(f"{API_BASE_URL}{path}", timeout=20) as response:
            return response.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"Image request failed: {error}") from error


def safe_json(path: str, default: object) -> object:
    try:
        return api_json(path)
    except RuntimeError as error:
        st.error(str(error))
        return default


st.title("DataGuard AI")
st.caption("Local data-quality investigation · simulated actions · evidence linked to pipeline runs")
st.markdown(f"<span class='dg-subtle'>Backend: {API_BASE_URL}</span>", unsafe_allow_html=True)

try:
    dashboard_summary = api_json("/api/v1/dashboard/summary")
except RuntimeError as error:
    st.error(str(error))
    st.info("Start the API with `uv run uvicorn datagard.main:app --app-dir src`.")
    st.stop()

page = st.sidebar.radio(
    "Workspace",
    ("Overview", "DQF processing", "Incident investigation", "Actions & approvals", "Evaluation"),
)
st.sidebar.markdown("---")
st.sidebar.markdown("**Prototype mode**")
st.sidebar.markdown("<span class='dg-badge'>SIMULATED ACTIONS</span>", unsafe_allow_html=True)
st.sidebar.caption("No external scheduler or production data system is connected.")


def render_overview() -> None:
    st.header("Pipeline overview")
    metrics = st.columns(4)
    metrics[0].metric("Pipelines", dashboard_summary["pipeline_count"])
    metrics[1].metric("Pipeline runs", dashboard_summary["run_count"])
    metrics[2].metric("Failed executions", dashboard_summary["failed_run_count"])
    metrics[3].metric("Open incidents", dashboard_summary["open_incident_count"])
    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Recent pipeline runs")
        runs = safe_json("/api/v1/runs?limit=12", [])
        if runs:
            st.dataframe([
                {"run_id": item["run_id"], "pipeline": item["pipeline_id"], "status": item["status"],
                 "input rows": item["input_rows"], "output rows": item["output_rows"], "duration ms": item["duration_ms"]}
                for item in runs
            ], use_container_width=True, hide_index=True)
        if st.button("Generate deterministic demo dataset", type="secondary"):
            st.json(api_json("/api/v1/demo/generate", method="POST"))
            st.rerun()
    with right:
        st.subheader("Incidents")
        incidents = safe_json("/api/v1/incidents", [])
        if incidents:
            st.dataframe([
                {"incident": item["incident_id"], "family": item["incident_family"],
                 "severity": item["severity"], "status": item["status"], "run": item["affected_run_id"]}
                for item in incidents[:12]
            ], use_container_width=True, hide_index=True)
        else:
            st.info("Analyze a run to create an incident from configured quality evidence.")
    st.caption("Detection in the API workflow uses the configured severity-rule baseline. The held-out Isolation Forest benchmark is shown on the Evaluation page.")


def render_dqf() -> None:
    st.header("DQF visual inspection")
    st.write("A fixed chronological window is encoded into a calibrated fingerprint. The saved intermediate and segmentation images below are served through the API.")
    artifacts = safe_json("/api/v1/dip/artifacts", [])
    if not artifacts:
        st.warning("No saved DQF windows are available. Run `uv run python -m datagard.visual_inspection` first.")
        return
    selected = st.selectbox("Fingerprint window", artifacts, format_func=lambda item: f"{item['artifact_id']} · {len(item['window_run_ids'])} runs")
    st.caption(f"Encoder {selected['encoder_version']} · baseline {selected['baseline_version']}")
    with st.expander("Axis mapping", expanded=False):
        st.write({"run rows": selected["run_map"], "metric channels": selected["channel_map"]})
    stages = (
        ("Raw DQF", "raw"),
        ("Validity mask", "validity"),
        ("Ground truth (synthetic evaluation)", "ground_truth"),
        ("DIP-B0 · global Otsu", "baseline"),
        ("DIP-P1 · adaptive + morphology", "improved"),
        ("DIP-B0 overlay", "baseline_overlay"),
        ("DIP-P1 overlay", "improved_overlay"),
    )
    for index in range(0, len(stages), 3):
        columns = st.columns(3)
        for column, (title, stage) in zip(columns, stages[index:index + 3]):
            with column:
                st.markdown(f"**{title}**")
                image_path = f"/api/v1/dip/artifacts/{selected['artifact_id']}/images/{stage}"
                st.image(api_image(image_path), use_container_width=True)
    st.caption("Masks are saved image-processing outputs. Missing telemetry is represented by the separate validity mask.")


def render_investigation() -> None:
    st.header("Incident investigation")
    runs = safe_json("/api/v1/runs?limit=1000", [])
    if not runs:
        st.info("No pipeline runs are available.")
        return
    selected_run = st.selectbox("Run to analyze", runs, format_func=lambda item: f"{item['run_id']} · {item['status']} · {item['started_at']}")
    if st.button("Analyze run", type="primary"):
        result = api_json(f"/api/v1/runs/{selected_run['run_id']}/analyze", method="POST")
        st.session_state["last_analysis"] = result
        st.rerun()
    incidents = safe_json("/api/v1/incidents", [])
    if not incidents:
        st.info("Analysis creates incidents only when configured structured quality evidence reaches the baseline severity policy.")
        return
    incident = st.selectbox("Incident", incidents, format_func=lambda item: f"{item['incident_family']} · {item['severity']} · {item['incident_id']}")
    if st.button("Investigate and retrieve runbooks"):
        state = api_json(f"/api/v1/incidents/{incident['incident_id']}/investigate", "POST", {"runbook_query": f"{incident['incident_family']} pipeline data quality"})
        st.session_state["selected_incident_id"] = incident["incident_id"]
        st.session_state["investigation_state"] = state
        st.rerun()
    details = safe_json(f"/api/v1/incidents/{incident['incident_id']}", {})
    state = details.get("agent_state") if isinstance(details, dict) else None
    if state:
        st.markdown(f"**Workflow state:** `{state['current_status']}` · **Run:** `{state['run_id']}`")
        findings = state.get("findings", [])
        with st.expander(f"Structured findings ({len(findings)})", expanded=True):
            st.dataframe([
                {"evidence ID": item["finding_id"], "rule": item["rule_id"], "field": item["field_id"],
                 "severity": item["severity"], "observed": item["observed"], "message": item["message"]}
                for item in findings
            ], use_container_width=True, hide_index=True)
        st.subheader("Ranked cause hypotheses")
        for hypothesis in state.get("rca_hypotheses", []):
            with st.expander(f"{hypothesis['rank']}. {hypothesis['cause_code']} · {hypothesis['summary']}"):
                st.write("Supporting evidence:", hypothesis["supporting_evidence_ids"])
                st.write("Missing / contradicting:", hypothesis["contradicting_or_missing_evidence"])
                st.write("Lineage:", {"upstream": hypothesis["upstream_nodes"], "downstream": hypothesis["downstream_nodes"]})
                st.write("Next check:", hypothesis["next_investigation"])
        st.subheader("Retrieved runbook sources")
        for reference in state.get("retrieved_runbook_refs", []):
            st.markdown(f"- `{reference}`")
    else:
        st.caption("Select an incident and investigate to compute RCA and source-linked runbook references.")


def render_actions() -> None:
    st.header("Action centre")
    incidents = safe_json("/api/v1/incidents", [])
    if not incidents:
        st.info("Create an incident from the Incident investigation page first.")
        return
    incident = st.selectbox("Incident with action proposals", incidents, format_func=lambda item: f"{item['incident_family']} · {item['incident_id']}")
    details = safe_json(f"/api/v1/incidents/{incident['incident_id']}", {})
    state = details.get("agent_state") if isinstance(details, dict) else None
    if not state:
        st.info("Run investigation first to receive typed action proposals.")
        return
    st.markdown(f"Workflow state: **{state['current_status']}**")
    proposals = state.get("action_proposals", [])
    if not proposals:
        st.info("No action plan was produced because the available evidence was inconclusive.")
        return
    for proposal in proposals:
        st.markdown(f"#### {proposal['tool_name'].replace('_', ' ').title()} · {proposal['risk_level']} risk")
        st.write(proposal["expected_outcome"])
        st.caption(f"Preconditions: {', '.join(proposal['preconditions'])} · Approval required: {proposal['requires_approval']}")
        st.caption(f"Evidence: {', '.join(proposal['evidence_refs']) or 'none'}")
        current = state["current_status"]
        pending = current == "AWAITING_APPROVAL" and proposal["requires_approval"] and proposal["action_id"] not in state["executed_action_ids"] and state["approval_status"] != "APPROVED"
        approved_ready = current == "AWAITING_APPROVAL" and proposal["requires_approval"] and proposal["action_id"] not in state["executed_action_ids"] and state["approval_status"] == "APPROVED"
        eligible = current == "PROPOSED" and proposal["action_id"] not in state["executed_action_ids"]
        if pending:
            with st.form(f"approval-{proposal['action_id']}"):
                role = st.text_input("Approver role", value=settings.actions.approval_role)
                reason = st.text_input("Approval reason", value="Reviewed evidence and isolated repair plan")
                approve, reject = st.columns(2)
                approved = approve.form_submit_button("Approve action", type="primary")
                rejected = reject.form_submit_button("Reject action")
                if approved or rejected:
                    decision = "APPROVED" if approved else "REJECTED"
                    api_json(f"/api/v1/actions/{proposal['action_id']}/approve", "POST", {"decision": decision, "approver_role": role, "reason": reason})
                    st.rerun()
        elif eligible or approved_ready:
            button_text = (
                f"Execute approved simulated {proposal['tool_name'].replace('_', ' ')}"
                if approved_ready else
                f"Request approval for simulated {proposal['tool_name'].replace('_', ' ')}"
                if proposal["requires_approval"] else
                f"Execute simulated {proposal['tool_name'].replace('_', ' ')}"
            )
            if st.button(button_text, key=f"execute-{proposal['action_id']}", type="primary" if proposal["requires_approval"] else "secondary"):
                response = api_json(f"/api/v1/actions/{proposal['action_id']}/execute", "POST")
                st.session_state["last_action_state"] = response
                st.rerun()
    if state.get("verification_result"):
        st.subheader("Post-action verification")
        st.json(state["verification_result"])
    timeline = safe_json(f"/api/v1/incidents/{incident['incident_id']}/timeline", [])
    with st.expander("Audit and state-transition timeline"):
        st.dataframe(timeline, use_container_width=True, hide_index=True)


def render_evaluation() -> None:
    st.header("Measured evaluation")
    summary = safe_json("/api/v1/evaluation/summary", {})
    detection = summary.get("detection") if isinstance(summary, dict) else None
    dip = summary.get("dip") if isinstance(summary, dict) else None
    if detection:
        st.subheader("Held-out incident detection")
        st.caption(f"Test runs: {detection['test_run_count']} · positives: {detection['test_positive_count']} · negatives: {detection['test_negative_count']}")
        st.dataframe([
            {"model": item["detector_name"], "n": item["sample_count"], "precision": item["precision"],
             "recall": item["recall"], "F1": item["f1"], "Average Precision": item["average_precision"],
             "TP": item["true_positive"], "FP": item["false_positive"], "FN": item["false_negative"], "TN": item["true_negative"]}
            for item in detection["metrics"]
        ], use_container_width=True, hide_index=True)
    if dip:
        st.subheader("Held-out DIP pixel segmentation")
        st.dataframe(list(dip["aggregate_metrics"].values()), use_container_width=True, hide_index=True)
        st.caption(f"Evaluated runs: {dip['evaluated_unique_run_count']} of {dip['held_out_run_count']} held out · valid pixels per method: {dip['valid_pixel_count_per_method']}")
    if not detection and not dip:
        st.warning("Run the documented benchmark commands to create evaluation outputs.")
    st.caption("Results are synthetic held-out measurements; they are not production accuracy claims.")


if page == "Overview":
    render_overview()
elif page == "DQF processing":
    render_dqf()
elif page == "Incident investigation":
    render_investigation()
elif page == "Actions & approvals":
    render_actions()
else:
    render_evaluation()
