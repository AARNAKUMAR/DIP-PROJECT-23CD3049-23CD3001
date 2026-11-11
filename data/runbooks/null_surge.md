# Null surge response

## Locate the affected fields

Review field-level null-rate findings, source payload changes, mapping defaults, and recent transformation releases. Compare upstream records with the target field contract.

## Recovery

Quarantine if a required field is materially incomplete. Do not replace nulls with guessed values. A repair must use an approved deterministic rule, write a separate artifact, preserve the original, and pass the relevant quality checks.
