"""Small SQLite JSON-record store for prototype domain and audit records."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel


_ENTITY_TYPES = frozenset({
    "runs", "findings", "incidents", "agent_states", "action_proposals", "approvals",
    "tool_audit_events", "state_transitions", "outcomes", "artifacts", "simulated_runs",
    "tool_states",
})


class SQLiteStore:
    """Persist strict application records without embedding domain logic in SQL."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS entity_records (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_id)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS entity_records_type_idx ON entity_records(entity_type, entity_id)"
            )

    def put(self, entity_type: str, entity_id: str, value: BaseModel | dict[str, Any]) -> None:
        """Upsert one JSON-compatible record by its stable domain identifier."""

        self._validate_type(entity_type)
        payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO entity_records(entity_type, entity_id, payload_json, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                     payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
                (entity_type, entity_id, encoded, datetime.now(timezone.utc).isoformat()),
            )

    def get(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        """Load one record, or return None when it does not exist."""

        self._validate_type(entity_type)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM entity_records WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, entity_type: str) -> tuple[dict[str, Any], ...]:
        """Load all records of one type in stable identifier order."""

        self._validate_type(entity_type)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM entity_records WHERE entity_type=? ORDER BY entity_id",
                (entity_type,),
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def delete(self, entity_type: str, entity_id: str) -> bool:
        """Delete a local record and report whether it existed."""

        self._validate_type(entity_type)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM entity_records WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
        return cursor.rowcount > 0

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_type(entity_type: str) -> None:
        if entity_type not in _ENTITY_TYPES:
            raise ValueError(f"Unsupported persistence entity type: {entity_type}")
