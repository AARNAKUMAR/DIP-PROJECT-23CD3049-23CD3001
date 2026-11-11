# DataGuard AI - IDE handoff

This pack defines the implementation baseline for HSR-AGAI-001 with a bounded DIP visual-inspection contribution.

## Read in this order

1. `AGENTS.md` - mandatory IDE operating rules and per-iteration workflow.
2. `ARCHITECTURE_AND_REQUIREMENTS.md` - canonical requirements, module ownership, contracts, stack, tests and checkpoints.
3. `ACTION.md` - current implementation state and append-only iteration ledger.
4. `architecture.png` - high-level architecture picture.
5. `DataGuard_AI_Architecture_Requirements_Report.docx` - formatted human-review copy of the requirements report.

## First instruction

Start at CP-0 only. Inspect the existing repository before editing. Do not scaffold or implement all modules at once. Stop and report when CP-0 acceptance conditions pass.

## Source-of-truth rule

The Markdown architecture report is the IDE-facing canonical requirements document. The DOCX is its formatted reading copy. `ACTION.md` is the live progress record, not a replacement for requirements. `AGENTS.md` controls how the IDE must work. Record and escalate conflicts; do not silently reconcile them.
