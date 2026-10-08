from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sqlite3
from typing import Any, Optional

DEFAULT_DB_NAME = "deep_trekker.sqlite3"
SECRET_KEY_MARKERS = {
    "api_key",
    "gemini_api_key",
    "anthropic_api_key",
    "thinking",
    "reasoning",
    "reasoning_content",
    "thinking_process",
    "thought",
}
SECRET_VALUE_RE = re.compile(r"(AIza[0-9A-Za-z_-]{10,}|sk-ant-[0-9A-Za-z_-]{10,})")


def default_sqlite_path() -> Path:
    from os import getenv

    override = getenv("DEEP_TREKKER_SQLITE")
    if override:
        path = Path(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    root = Path(__file__).resolve().parents[1]
    directory = root / "runtime"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / DEFAULT_DB_NAME


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    if getattr(connection, "is_postgres", False):
        return
    existing = table_columns(connection, table)
    for name, definition in columns.items():
        if name in existing:
            continue
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def lifecycle_where(view: str, *, completed_statuses: tuple[str, ...] = ("COMPLETED", "APPROVED")) -> str:
    deleted_null = "(deleted_at IS NULL OR deleted_at = '')"
    archived_null = "(archived_at IS NULL OR archived_at = '')"
    completed = ", ".join(f"'{item}'" for item in completed_statuses)
    if view == "history":
        return "(deleted_at IS NULL OR deleted_at = '')"
    if view == "trash":
        return "(deleted_at IS NOT NULL AND deleted_at != '')"
    if view == "archived":
        return f"{deleted_null} AND archived_at IS NOT NULL AND archived_at != ''"
    if view == "completed":
        return f"{deleted_null} AND {archived_null} AND status IN ({completed})"
    if view == "in_progress":
        return f"{deleted_null} AND {archived_null} AND IFNULL(status, '') NOT IN ({completed})"
    return f"{deleted_null} AND {archived_null}"


def connect_sqlite(path: Optional[Path] = None) -> sqlite3.Connection:
    # DATABASE_URL present -> central PostgreSQL for the default database; otherwise local SQLite (v1).
    # An explicit non-default path (tests, tools) always stays SQLite.
    from repositories.settings import database_url

    url = database_url()
    if url and (path is None or Path(path).resolve() == default_sqlite_path().resolve()):
        from repositories.postgres import PostgresConnection

        return PostgresConnection(url)
    resolved = Path(path) if path else default_sqlite_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dumps_json(payload: Any) -> str:
    return json.dumps(strip_secrets(payload), ensure_ascii=False)


def loads_json(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return {} if default is None else default
    return json.loads(text)


def strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).casefold() in SECRET_KEY_MARKERS:
                continue
            cleaned[key] = strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_RE.sub("[redacted]", value)
    return value
