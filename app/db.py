"""Postgres for the shared trade log (Step 2b.3), behind the same small interface the trade log
already uses with SQLite: execute(sql, params) -> cursor with fetchone/fetchall/lastrowid, rows
readable as row["col"] or row[0], executescript, commit, close.

The trade log's SQL is written for SQLite; here it is translated on the way through:
    ? placeholders                -> %s
    INSERT INTO <table with id>   -> ... RETURNING id   (so lastrowid works)
    id INTEGER PRIMARY KEY        -> id BIGSERIAL PRIMARY KEY   (schema only)
Autocommit is on (each statement is its own transaction). A dropped connection (e.g. the database
restarting) is reopened once and the statement retried.
"""

from __future__ import annotations

import logging
import re
import threading

log = logging.getLogger(__name__)
ID_TABLES = {"runs", "signals", "alerts", "responses", "orders", "trade_events", "fleet_commands"}
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)


class Row(dict):
    """A row readable by column name (row["id"]) or position (row[0]), like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self):
        return list(super().keys())


def _row_factory(cursor):
    names = [d.name for d in cursor.description] if cursor.description else []

    def make(values):
        return Row(zip(names, values))
    return make


def pg_schema(sqlite_schema: str) -> str:
    return re.sub(r"(\n\s*id\s+)INTEGER PRIMARY KEY", r"\1BIGSERIAL PRIMARY KEY", sqlite_schema)


class _Result:
    def __init__(self, rows: list[Row] | None, lastrowid=None):
        self._rows = rows or []
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class PgConnection:
    def __init__(self, url: str, schema: str | None = None):
        self.url, self.schema = url, schema
        self._lock = threading.Lock()
        self.lastrowid = None
        self._connect()

    def _connect(self):
        import psycopg
        opts = f"-c search_path={self.schema}" if self.schema else None
        self.conn = psycopg.connect(self.url, autocommit=True, connect_timeout=15, options=opts,
                                    row_factory=_row_factory)

    def _run(self, sql: str, params=()):
        import psycopg
        for attempt in (1, 2):
            try:
                with self._lock:
                    cur = self.conn.execute(sql, params)
                    rows = cur.fetchall() if cur.description else None
                return rows
            except psycopg.OperationalError:
                if attempt == 2:
                    raise
                log.warning("database connection lost; reconnecting")
                self._connect()

    def execute(self, sql: str, params=()) -> _Result:
        q = sql.replace("%", "%%").replace("?", "%s")
        m = _INSERT.match(q)
        add_id = m and m.group(1).lower() in ID_TABLES and "returning" not in q.lower()
        if add_id:
            q = q.rstrip().rstrip(";") + " RETURNING id"
        rows = self._run(q, tuple(params))
        self.lastrowid = rows[0]["id"] if add_id and rows else None     # cursor-style access too
        return _Result(rows, lastrowid=self.lastrowid)

    def executescript(self, script: str) -> None:
        self._run(script)

    def cursor(self) -> "PgConnection":
        return self

    def commit(self) -> None:
        pass                                  # autocommit

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass

    def columns(self, table: str) -> set[str]:
        rows = self._run("SELECT column_name FROM information_schema.columns WHERE table_name = %s"
                         + (" AND table_schema = %s" if self.schema else " AND table_schema = current_schema()"),
                         (table, self.schema) if self.schema else (table,))
        return {r["column_name"] for r in rows or []}
