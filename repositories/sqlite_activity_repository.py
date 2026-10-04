from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from models import ActivityEvent
from repositories.sqlite import connect_sqlite, default_sqlite_path, dumps_json, loads_json, now_iso


class SqliteActivityRepository:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_sqlite_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = connect_sqlite(self.path)
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                entity_kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_version INTEGER,
                customer_name TEXT,
                title TEXT,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_events_entity ON activity_events(entity_kind, entity_id, occurred_at DESC)"
        )
        self._connection.commit()

    def append(self, event: ActivityEvent) -> ActivityEvent:
        stored = event
        if not stored.event_id:
            stored = event.model_copy(update={"event_id": f"EVT-{uuid4().hex[:12].upper()}"})
        if not stored.occurred_at:
            stored = stored.model_copy(update={"occurred_at": now_iso()})
        self._connection.execute(
            """
            INSERT INTO activity_events (
                event_id, event_type, occurred_at, entity_kind, entity_id,
                entity_version, customer_name, title, payload_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored.event_id,
                stored.event_type,
                stored.occurred_at,
                stored.entity_kind,
                stored.entity_id,
                stored.entity_version,
                stored.customer_name,
                stored.title,
                dumps_json(stored.payload),
                stored.schema_version,
            ),
        )
        self._connection.commit()
        return stored

    def list_events(
        self,
        *,
        entity_kind: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[ActivityEvent]:
        sql = "SELECT * FROM activity_events"
        params: list = []
        clauses = []
        if entity_kind:
            clauses.append("entity_kind = ?")
            params.append(entity_kind)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self._connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def has_event(
        self,
        *,
        event_type: str,
        entity_kind: str,
        entity_id: str,
        entity_version: Optional[int] = None,
    ) -> bool:
        sql = "SELECT 1 FROM activity_events WHERE event_type = ? AND entity_kind = ? AND entity_id = ?"
        params: list = [event_type, entity_kind, entity_id]
        if entity_version is not None:
            sql += " AND entity_version = ?"
            params.append(entity_version)
        sql += " LIMIT 1"
        return self._connection.execute(sql, params).fetchone() is not None

    def update(self, event: ActivityEvent) -> ActivityEvent:
        raise RuntimeError("activity_events are append-only")

    def latest_for_entities(self, kind: str, entity_ids: list[str]) -> dict[str, str]:
        if not entity_ids:
            return {}
        placeholders = ", ".join("?" for _ in entity_ids)
        rows = self._connection.execute(
            f"""
            SELECT entity_id, MAX(occurred_at) AS latest
            FROM activity_events
            WHERE entity_kind = ? AND entity_id IN ({placeholders})
            GROUP BY entity_id
            """,
            [kind, *entity_ids],
        ).fetchall()
        return {row["entity_id"]: row["latest"] for row in rows}

    def _from_row(self, row) -> ActivityEvent:
        return ActivityEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            entity_kind=row["entity_kind"],
            entity_id=row["entity_id"],
            entity_version=row["entity_version"],
            customer_name=row["customer_name"],
            title=row["title"],
            payload=loads_json(row["payload_json"], default={}),
            schema_version=row["schema_version"],
        )
