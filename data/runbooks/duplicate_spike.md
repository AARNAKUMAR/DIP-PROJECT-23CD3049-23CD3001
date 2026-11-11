# Duplicate-key spike response

## Inspect key generation

Check duplicate counts and rates, source key stability, join cardinality, and retry behavior. Distinguish legitimate repeated business events from duplicate records before deduplicating.

## Recovery

Hold the affected batch if duplicate keys can corrupt downstream aggregates. Any deduplication must define a stable winner rule, create a new output artifact, and preserve the input. Verify key uniqueness and row counts after the simulated repair.
