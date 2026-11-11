# Row-count drop response

## Trace the missing volume

Compare input and output rows with recent runs. Inspect upstream dependencies, source partitions, filters, and failed stages. A row-count drop is observed evidence; it does not by itself prove data loss.

## Recovery

Keep the output quarantined while the upstream source is checked. A simulated rerun is appropriate only after confirming input availability and idempotency. Compare the rerun count and quality findings with the original before considering resolution.
