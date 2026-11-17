"""The trade log: one SQLite file (data/tradelog.db) that live days, replays and backtests all write to.

    runs       one batch of signals made with the same settings: a live day, a replay, a backtest
    signals    one triggered breakout and its full plan (entry, stop, target, size, risk, odds)
    alerts     whether a signal was sent to Discord, or held back and why
    responses  your button taps
    outcomes   what each signal did after the close (target / stop / flat), in R and dollars

Every run and signal carries `strategy` (e.g. "orb") and `source` ("live" / "replay" / "backtest"),
and every run stores a snapshot of its settings and the git commit, so any two runs can be compared.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app import paths
from app.pipeline import SignalResult

DEFAULT_DB = paths.DATA_DIR / "tradelog.db"
SOURCES = ("live", "replay", "backtest")
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    strategy      TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('live', 'replay', 'backtest')),
    label         TEXT,
    date_from     TEXT,
    date_to       TEXT,
    settings_json TEXT NOT NULL,       -- strategy settings + risk rules in effect
    code_version  TEXT,                -- git commit (+ "-dirty" for uncommitted changes)
    started_at    TEXT NOT NULL,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id               INTEGER PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES runs(id),
    strategy         TEXT NOT NULL,
    source           TEXT NOT NULL,
    date             TEXT NOT NULL,     -- session date, New York
    symbol           TEXT NOT NULL,
    status           TEXT NOT NULL,     -- pass / blocked / refused / error
    reason           TEXT,
    trigger_time     TEXT,              -- e.g. "10:15" (bar close, New York)
    trigger_price    REAL,
    or_high          REAL,
    or_low           REAL,
    volume_x         REAL,
    entry            REAL,
    stop             REAL,
    target           REAL,
    target_r         REAL,
    risk_per_share   REAL,
    qty              INTEGER,
    max_loss         REAL,
    risk_verdict     TEXT,              -- PASS / BLOCK
    risk_reasons     TEXT,              -- JSON list
    tm_p_target      REAL,
    tm_p_stop        REAL,
    tm_p_neither     REAL,
    tm_avg_r         REAL,
    tm_verdict       TEXT,
    folder           TEXT,              -- runs/<date>/<strategy>/<TICKER>/ (live and replay)
    created_at       TEXT NOT NULL,
    UNIQUE (run_id, date, symbol)       -- an ORB fires at most once per stock per day
);
CREATE INDEX IF NOT EXISTS signals_by_day ON signals (strategy, source, date);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY,
    signal_id    INTEGER NOT NULL UNIQUE REFERENCES signals(id),
    sent         INTEGER NOT NULL,      -- 1 = posted to Discord, 0 = held back
    held_reason  TEXT,                  -- e.g. "daily alert cap (5)", "risk BLOCK"
    channel_id   TEXT,
    message_id   TEXT,
    at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    id         INTEGER PRIMARY KEY,
    signal_id  INTEGER NOT NULL REFERENCES signals(id),
    action     TEXT NOT NULL CHECK (action IN ('took', 'skip')),
    user_id    TEXT,
    at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    signal_id    INTEGER PRIMARY KEY REFERENCES signals(id),
    result       TEXT NOT NULL CHECK (result IN ('target', 'stop', 'flat', 'no_data')),
    exit_price   REAL,
    exit_time    TEXT,
    r_multiple   REAL,
    pnl_usd      REAL,
    method       TEXT NOT NULL,         -- how it was worked out, e.g. "5m bars, stop first on ties"
    resolved_at  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code_version() -> str | None:
    """The git commit the code came from. On Railway there's no .git folder, but Railway
    passes the commit in RAILWAY_GIT_COMMIT_SHA."""
    import os
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    if sha:
        return sha[:7]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=paths.REPO_ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=paths.REPO_ROOT,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def is_signal(result: SignalResult) -> bool:
    """True once the entry triggered. 'waiting' / 'expired' checks are not signals."""
    return (result.entry or {}).get("status") == "triggered"


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


class TradeLog:
    def __init__(self, path: Path = DEFAULT_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ runs

    def start_run(self, strategy: str, source: str, settings: dict, *, label: str | None = None,
                  date_from: str | None = None, date_to: str | None = None) -> int:
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        cur = self.db.execute(
            "INSERT INTO runs (strategy, source, label, date_from, date_to, settings_json,"
            " code_version, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (strategy, source, label, date_from, date_to, json.dumps(settings, sort_keys=True),
             code_version(), _now()))
        self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int) -> None:
        self.db.execute("UPDATE runs SET finished_at = ? WHERE id = ?", (_now(), run_id))
        self.db.commit()

    def find_day_run(self, strategy: str, source: str, day: str) -> sqlite3.Row | None:
        """The latest run for one day (a live day resumes it after a restart)."""
        return self.db.execute(
            "SELECT * FROM runs WHERE strategy = ? AND source = ? AND date_from = ? AND date_to = ?"
            " ORDER BY id DESC LIMIT 1", (strategy, source, day, day)).fetchone()

    def run(self, run_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    # --------------------------------------------------------------- signals

    def record_signal(self, run_id: int, result: SignalResult) -> int:
        """Save a triggered signal and its plan. A rerun of the same signal in the same run replaces it."""
        if not is_signal(result):
            raise ValueError(f"{result.symbol} did not trigger ({result.status}); not a signal")
        run = self.run(run_id)
        if run is None:
            raise ValueError(f"no run {run_id}")
        if run["strategy"] != result.strategy:
            raise ValueError(f"run {run_id} is {run['strategy']!r}, signal is {result.strategy!r}")

        e = result.entry or {}
        trig = e.get("trigger") or {}
        orng = e.get("opening_range") or {}
        plan = result.plan or {}
        order = result.order or {}
        risk = result.risk or {}
        tm = result.data("timemachine") or {}
        mc = tm.get("mc") or {}

        row = {
            "run_id": run_id, "strategy": result.strategy, "source": run["source"],
            "date": result.date, "symbol": result.symbol, "status": result.status,
            "reason": result.reason or None,
            "trigger_time": trig.get("close_time"), "trigger_price": _f(trig.get("price")),
            "or_high": _f(orng.get("high")), "or_low": _f(orng.get("low")),
            "volume_x": _f(trig.get("volume_x")),
            "entry": _f(plan.get("entry")), "stop": _f(plan.get("stop")),
            "target": _f(plan.get("target")), "target_r": _f(plan.get("target_r")),
            "risk_per_share": _f(plan.get("risk_per_share")),
            "qty": int(order["qty"]) if order.get("qty") else None,
            "max_loss": _f(risk.get("max_loss") or (order.get("plan") or {}).get("max_loss")),
            "risk_verdict": risk.get("verdict"),
            "risk_reasons": json.dumps(risk.get("reasons", [])) if risk else None,
            "tm_p_target": _f(mc.get("p_target")), "tm_p_stop": _f(mc.get("p_stop")),
            "tm_p_neither": _f(mc.get("p_neither")), "tm_avg_r": _f(mc.get("avg_R")),
            "tm_verdict": tm.get("verdict"),
            "folder": str(result.folder) if result.folder else None,
            "created_at": _now(),
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        updates = ", ".join(f"{c} = excluded.{c}" for c in row if c not in ("run_id", "date", "symbol"))
        self.db.execute(
            f"INSERT INTO signals ({cols}) VALUES ({marks}) "
            f"ON CONFLICT (run_id, date, symbol) DO UPDATE SET {updates}",
            tuple(row.values()))
        self.db.commit()
        return self.db.execute(
            "SELECT id FROM signals WHERE run_id = ? AND date = ? AND symbol = ?",
            (run_id, result.date, result.symbol)).fetchone()["id"]

    def signal(self, signal_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()

    def signals(self, *, strategy: str | None = None, source: str | None = None,
                date: str | None = None, run_id: int | None = None) -> list[sqlite3.Row]:
        where, args = [], []
        for col, val in (("strategy", strategy), ("source", source), ("date", date), ("run_id", run_id)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT * FROM signals" + (" WHERE " + " AND ".join(where) if where else "")
        return self.db.execute(sql + " ORDER BY date, trigger_time, symbol", args).fetchall()

    # ---------------------------------------------------------------- alerts

    def record_alert(self, signal_id: int, *, sent: bool, held_reason: str | None = None,
                     channel_id: int | str | None = None, message_id: int | str | None = None) -> None:
        if not sent and not held_reason:
            raise ValueError("a held-back alert needs a reason")
        self.db.execute(
            "INSERT INTO alerts (signal_id, sent, held_reason, channel_id, message_id, at)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (signal_id) DO UPDATE SET sent = excluded.sent,"
            " held_reason = excluded.held_reason, channel_id = excluded.channel_id,"
            " message_id = excluded.message_id, at = excluded.at",
            (signal_id, int(sent), held_reason,
             None if channel_id is None else str(channel_id),
             None if message_id is None else str(message_id), _now()))
        self.db.commit()

    def alerts_sent(self, *, strategy: str, date: str, source: str = "live", run_id: int | None = None) -> int:
        """How many alerts went out on a day. With run_id, only that run's (the daily cap counts per
        run, so replaying the same day twice doesn't share one cap)."""
        sql = ("SELECT COUNT(*) FROM alerts a JOIN signals s ON s.id = a.signal_id"
               " WHERE a.sent = 1 AND s.strategy = ? AND s.date = ? AND s.source = ?")
        args: list = [strategy, date, source]
        if run_id is not None:
            sql += " AND s.run_id = ?"
            args.append(run_id)
        return self.db.execute(sql, args).fetchone()[0]

    def alert(self, signal_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM alerts WHERE signal_id = ?", (signal_id,)).fetchone()

    # ------------------------------------------------------------- responses

    def record_response(self, signal_id: int, action: str, user_id: int | str | None = None) -> None:
        if action not in ("took", "skip"):
            raise ValueError("action must be 'took' or 'skip'")
        self.db.execute("INSERT INTO responses (signal_id, action, user_id, at) VALUES (?, ?, ?, ?)",
                        (signal_id, action, None if user_id is None else str(user_id), _now()))
        self.db.commit()

    def latest_response(self, signal_id: int) -> sqlite3.Row | None:
        """Your last tap counts (you can change your mind)."""
        return self.db.execute("SELECT * FROM responses WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
                               (signal_id,)).fetchone()

    # -------------------------------------------------------------- outcomes

    def record_outcome(self, signal_id: int, *, result: str, method: str,
                       exit_price: float | None = None, exit_time: str | None = None) -> None:
        """R and dollars are worked out here from the signal's own plan, so every source counts the same way."""
        sig = self.signal(signal_id)
        if sig is None:
            raise ValueError(f"no signal {signal_id}")
        r_mult = pnl = None
        if exit_price is not None and sig["entry"] is not None and sig["risk_per_share"]:
            r_mult = round((exit_price - sig["entry"]) / sig["risk_per_share"], 3)
            if sig["qty"]:
                pnl = round((exit_price - sig["entry"]) * sig["qty"], 2)
        self.db.execute(
            "INSERT INTO outcomes (signal_id, result, exit_price, exit_time, r_multiple, pnl_usd, method,"
            " resolved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (signal_id) DO UPDATE SET"
            " result = excluded.result, exit_price = excluded.exit_price, exit_time = excluded.exit_time,"
            " r_multiple = excluded.r_multiple, pnl_usd = excluded.pnl_usd, method = excluded.method,"
            " resolved_at = excluded.resolved_at",
            (signal_id, result, exit_price, exit_time, r_mult, pnl, method, _now()))
        self.db.commit()

    def outcome(self, signal_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM outcomes WHERE signal_id = ?", (signal_id,)).fetchone()

    def unresolved(self, *, strategy: str, date: str) -> list[sqlite3.Row]:
        """Signals from a day that don't have an outcome yet (for the after-close step)."""
        return self.db.execute(
            "SELECT s.* FROM signals s LEFT JOIN outcomes o ON o.signal_id = s.id"
            " WHERE s.strategy = ? AND s.date = ? AND o.signal_id IS NULL AND s.entry IS NOT NULL",
            (strategy, date)).fetchall()


def rows_as_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]
