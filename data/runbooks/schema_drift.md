# Schema drift response

## Confirm the contract change

Compare the observed schema with the registered version. Identify added, removed, renamed, and type-changed fields, then check downstream consumers and the producer release. Preserve the source batch while compatibility is unresolved. Do not automatically alter a published schema.

## Recovery

Quarantine the affected batch when consumers may misread fields. Ask the data owner to approve a compatible contract or an isolated repair. Rerun only after the producer and downstream contract are aligned, then verify schema and row-level quality findings.
