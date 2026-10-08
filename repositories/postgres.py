from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Optional, Sequence

# The SQLite repositories are reused unchanged on PostgreSQL: this adapter exposes the small
# sqlite3.Connection surface they use (execute / commit / close / context manager) and maps
# psycopg errors to sqlite3 error types so the existing error handling keeps working.

_COLLATE_NOCASE = re.compile(r"(\w+)\s+COLLATE\s+NOCASE", re.IGNORECASE)
_IFNULL = re.compile(r"\bIFNULL\(", re.IGNORECASE)

_lock = threading.Lock()
_shared: dict[str, Any] = {}


class PostgresError(sqlite3.DatabaseError):
    pass


class PostgresIntegrityError(sqlite3.IntegrityError):
    pass


def translate_sql(sql: str) -> str:
    sql = sql.replace("%", "%%").replace("?", "%s")
    sql = _IFNULL.sub("COALESCE(", sql)
    return _COLLATE_NOCASE.sub(r"lower(\1)", sql)


class _Row(dict):
    """dict row that also supports positional access like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []

    def make(values):
        return _Row(zip(names, values))

    return make


def _connect(url: str):
    import psycopg

    # autocommit: every statement sees the latest committed data from other users.
    # prepare_threshold=None: compatible with the Supabase connection pooler.
    return psycopg.connect(url, autocommit=True, row_factory=_row_factory, prepare_threshold=None)


def _shared_connection(url: str, *, reset: bool = False):
    with _lock:
        connection = _shared.get(url)
        if reset or connection is None or connection.closed or getattr(connection, "broken", False):
            connection = _connect(url)
            _shared[url] = connection
        return connection


def _map_error(error: Exception) -> sqlite3.Error:
    import psycopg

    if isinstance(error, psycopg.IntegrityError):
        return PostgresIntegrityError(str(error))
    return PostgresError(str(error))


class PostgresConnection:
    is_postgres = True

    def __init__(self, url: str):
        self._url = url
        self._transaction = None

    def execute(self, sql: str, params: Optional[Sequence] = None):
        import psycopg

        query = translate_sql(sql)
        values = tuple(params or ())
        try:
            return _shared_connection(self._url).execute(query, values)
        except psycopg.OperationalError:
            if self._transaction is not None:
                raise
            # One reconnect for idle connections dropped by the server.
            try:
                return _shared_connection(self._url, reset=True).execute(query, values)
            except psycopg.Error as error:
                raise _map_error(error) from error
        except psycopg.Error as error:
            raise _map_error(error) from error

    def executescript(self, script: str) -> None:
        # Schema is managed by deploy/postgres_schema.sql, never by app start-up.
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        # Process-wide shared connection; closing one repository must not close it for others.
        return None

    def __enter__(self):
        self._transaction = _shared_connection(self._url).transaction()
        self._transaction.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        transaction, self._transaction = self._transaction, None
        return transaction.__exit__(exc_type, exc, tb)


def is_postgres(connection) -> bool:
    return bool(getattr(connection, "is_postgres", False))
