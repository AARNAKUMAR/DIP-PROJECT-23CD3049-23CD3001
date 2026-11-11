# AGENTS.md - IDE operating contract

Read these files before changing code:

1. `ARCHITECTURE_AND_REQUIREMENTS.md` - authoritative project requirements and architecture.
2. `ACTION.md` - current project state and codebase change history.
3. `README.md` and relevant `docs/` files once they exist.

## Mission

Build one integrated, reproducible local prototype of HSR-AGAI-001. Keep the original data-quality incident detection, RCA, RAG and remediation requirements intact. Add DIP as a bounded visual-evidence module that consumes canonical telemetry. Do not convert the project into a generic computer-vision application.

## Hard rules

- Work checkpoint-by-checkpoint. Start with CP-0 only. Do not scaffold every module or implement every layer in one prompt.
- Before editing, inspect the repository and search for existing logic. Reuse existing functions/services/contracts where possible.
- State the requirement IDs and smallest expected file set before each task.
- Keep a Python modular monolith. No microservices.
- `quality/` is the sole owner of structured quality rules. DIP must not duplicate those checks.
- `features/` is the sole owner of canonical ML feature construction.
- `dip/encoder.py` is the sole owner of fingerprint encoding; `dip/processor.py` owns image operations.
- `detection/` owns anomaly scoring; `rca/` owns cause hypotheses; `rag/` owns runbook retrieval.
- `agent/orchestrator.py` is the single coordinator/state-transition owner. API and UI must not recreate this flow.
- `tools/` is the only route for state-changing actions. Enforce permissions and preconditions server-side.
- Never execute arbitrary LLM-generated code, SQL, shell commands or filesystem paths.
- All repair/rerun operations are simulated and local. Preserve originals; write repaired output to a separate artifact.
- LLM provider is optional. Core demo must work without an API key.
- All tunable thresholds and model/DIP/agent parameters belong in central configuration; avoid magic numbers.
- Configure logging once. Modules use `logging.getLogger(__name__)`. Persist agent/tool audit events in the database separately.
- Use type hints, descriptive names, small functions and explicit error handling. Avoid giant files/classes and unnecessary abstraction layers.
- Do not add dependencies or infrastructure without documenting the requirement, alternative and trade-off first.
- Do not create placeholder modules, fake metrics, hard-coded success data or pretend integrations.
- Do not refactor unrelated code during a feature task.
- Update tests and relevant documentation in the same iteration. Use `ACTION.md` only for changes affecting source code, tests, configuration, reproducible data/evaluation artifacts, or runtime behavior. Exclude README-only or presentation-only edits, formatting, and branch/history administration. Keep applicable entries chronological; remove out-of-scope historic entries only when the project owner explicitly directs it.
- If a requirement conflicts with the architecture, stop and record the conflict in `ACTION.md` and `docs/decisions.md`; do not resolve it silently.

## Required loop for each task

1. Read the current `ACTION.md` state and relevant requirements.
2. Inspect existing modules/tests and search for duplicate logic.
3. State requirement IDs, intended changes and dependencies.
4. Implement the smallest vertical slice.
5. Run targeted unit/integration tests and report exact commands/results.
6. Inspect changed files for duplicated business logic and configuration literals.
7. Update README/docs/config examples as needed.
8. Refresh the `ACTION.md` current-state summary; append a ledger entry only when the change affects the codebase as defined above.
9. Report changed files, tests, blockers and next smallest task.

## Required iteration report

```text
Iteration: CP-X / task name
Requirement IDs: G-xx, NFR-xx
Plan completed: ...
Files changed: ...
Existing logic reused: ...
New logic added (and why it was not duplicative): ...
Tests/commands run: ...
Results: PASS / FAIL / NOT RUN (with reason)
Config/docs/ACTION.md updated: yes/no
Known risks/blockers: ...
Next smallest task: ...
```

## First task: CP-0 only

- Inspect the existing repository and summarize its structure before modifying it.
- Create only the minimum package skeleton, `pyproject.toml`, central configuration loader, central logging setup and minimal FastAPI health endpoint if needed.
- Add configuration and health smoke tests.
- Create/update `docs/decisions.md` and `ACTION.md`.
- Stop when CP-0 acceptance conditions in the architecture report pass. Do not begin ingestion, DIP, ML, RAG, database schema, agent tools or dashboard until then.
