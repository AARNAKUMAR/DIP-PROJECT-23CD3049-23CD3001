"""In-memory schema registry, schema comparison, and pipeline lineage."""

from dataclasses import dataclass

from datagard.contracts import SchemaField


@dataclass(frozen=True)
class SchemaDiff:
    """Structured changes between expected and observed schemas."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    renamed: tuple[tuple[str, str], ...]
    type_changed: tuple[tuple[str, str, str], ...]


class SchemaRegistry:
    """Store ordered schema versions and calculate changes in one place."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str], tuple[SchemaField, ...]] = {}

    def register(self, pipeline_id: str, version: str, fields: tuple[SchemaField, ...]) -> None:
        self._schemas[(pipeline_id, version)] = fields

    def get(self, pipeline_id: str, version: str) -> tuple[SchemaField, ...] | None:
        return self._schemas.get((pipeline_id, version))

    @staticmethod
    def diff(expected: tuple[SchemaField, ...], observed: tuple[SchemaField, ...]) -> SchemaDiff:
        expected_by_id = {field.field_id: field for field in expected}
        observed_by_id = {field.field_id: field for field in observed}
        shared_ids = expected_by_id.keys() & observed_by_id.keys()
        return SchemaDiff(
            added=tuple(sorted(observed_by_id.keys() - expected_by_id.keys())),
            removed=tuple(sorted(expected_by_id.keys() - observed_by_id.keys())),
            renamed=tuple(
                sorted(
                    (expected_by_id[field_id].name, observed_by_id[field_id].name)
                    for field_id in shared_ids
                    if expected_by_id[field_id].name != observed_by_id[field_id].name
                )
            ),
            type_changed=tuple(
                sorted(
                    (
                        expected_by_id[field_id].name,
                        expected_by_id[field_id].data_type,
                        observed_by_id[field_id].data_type,
                    )
                    for field_id in shared_ids
                    if expected_by_id[field_id].data_type != observed_by_id[field_id].data_type
                )
            ),
        )


class LineageGraph:
    """Small directed adjacency map for pipeline dependencies."""

    def __init__(self) -> None:
        self._upstream: dict[str, set[str]] = {}

    def add_dependency(self, pipeline_id: str, upstream_pipeline_id: str) -> None:
        self._upstream.setdefault(pipeline_id, set()).add(upstream_pipeline_id)

    def upstream_of(self, pipeline_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._upstream.get(pipeline_id, set())))

    def downstream_of(self, pipeline_id: str) -> tuple[str, ...]:
        return tuple(sorted(target for target, sources in self._upstream.items() if pipeline_id in sources))
