# Safe simulated rerun

## Preconditions

Confirm the pipeline and source run are known, the incident is open, inputs remain available, and the operation is idempotent or isolated. This prototype records a local simulation only; it does not call an external scheduler.

## Verification

Create a distinct simulated run record and preserve the original. Re-evaluate applicable quality rules and compare output counts and schema. Keep the incident open or escalate if the defect remains.
