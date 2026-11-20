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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from app import paths
from app.outcomes import Outcome
from app.pipeline import SignalResult

DEFAULT_DB = paths.DATA_DIR / "tradelog.db"
SOURCES = ("live", "replay", "backtest")
SCHEMA_VERSION = 2

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

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY,
    signal_id        INTEGER NOT NULL REFERENCES signals(id),
    client_order_id  TEXT NOT NULL UNIQUE,  -- orb-<date>-<signal id>: a retry can never double-order
    broker_order_id  TEXT,
    symbol           TEXT NOT NULL,
    qty              INTEGER NOT NULL,
    limit_price      REAL,
    stop             REAL,
    target           REAL,
    status           TEXT NOT NULL,         -- submitted / filled / partially_filled / cancelled / rejected / closed
    submitted_at     TEXT NOT NULL,
    filled_qty       INTEGER,
    filled_price     REAL,
    filled_at        TEXT,
    exit_reason      TEXT,                  -- stop / target / flat (1b.5)
    exit_price       REAL,
    exited_at        TEXT,
    pnl_usd          REAL,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS heartbeats (
    bot      TEXT PRIMARY KEY,            -- e.g. orb: one row per bot, updated every minute (2b.3)
    at       TEXT NOT NULL,
    note     TEXT
);

CREATE TABLE IF NOT EXISTS fleet_settings (
    key         TEXT PRIMARY KEY,         -- e.g. global_pause (set by the head bot, read by every bot)
    value       TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS fleet_commands (
    id          INTEGER PRIMARY KEY,
    command     TEXT NOT NULL,            -- e.g. flatten (posted by the head bot, carried out by every bot) (2b.4)
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS fleet_command_acks (
    command_id  INTEGER NOT NULL,
    bot         TEXT NOT NULL,            -- the bot that carried it out
    at          TEXT NOT NULL,
    result      TEXT,
    PRIMARY KEY (command_id, bot)
);

CREATE TABLE IF NOT EXISTS daily_reports (
    bot   TEXT NOT NULL,                  -- each bot's full after-close summary; the head bot posts them (2b.4)
    day   TEXT NOT NULL,
    text  TEXT NOT NULL,
    at    TEXT NOT NULL,
    PRIMARY KEY (bot, day)
);

CREATE TABLE IF NOT EXISTS trade_events (
    id               INTEGER PRIMARY KEY,
    client_order_id  TEXT NOT NULL,
    at               TEXT NOT NULL,
    kind             TEXT NOT NULL,          -- stop_moved / target_moved / breakeven / closed_manually / cancelled
    old_value        REAL,
    new_value        REAL,
    note             TEXT
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

# columns added after the first version (added to existing databases on open)
MIGRATIONS = {
    "orders": [("stop_order_id", "TEXT"), ("target_order_id", "TEXT"), ("entry_slippage", "REAL"),
               ("exit_slippage", "REAL"), ("live_card_channel_id", "TEXT"), ("live_card_message_id", "TEXT"),
               ("closed_card_message_id", "TEXT")],
    "outcomes": [("r_gross", "REAL"), ("cost_usd", "REAL"), ("mfe_r", "REAL"), ("mae_r", "REAL"),
                 ("bars_held", "INTEGER")],
}


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
    """True once the entry triggered. 'waiting' / 'expired' checks are not signals, and neither is a
    chart the live scan's filters skip (price floor, missing bar)."""
    return (result.entry or {}).get("status") == "triggered" and result.status != "skipped"


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def database_url() -> str | None:
    """The shared Postgres (Step 2b.3), set on Railway as DATABASE_URL. None = local SQLite."""
    import os
    return (os.environ.get("DATABASE_URL") or "").strip() or None


class TradeLog:
    """The live trade log uses the shared Postgres when DATABASE_URL is set; replays, backtests and
    tests (which pass their own file) always use SQLite."""

    def __init__(self, path: Path = DEFAULT_DB, *, url: str | None = None, schema: str | None = None):
        if url is None and path == DEFAULT_DB:
            url = database_url()
        import os
        test_pg = os.environ.get("TRADELOG_TEST_PG_URL")
        if test_pg and url is None:                     # tests only: run this log on Postgres instead,
            import hashlib                              # in a fresh schema per test file
            url, schema = test_pg, "t_" + hashlib.md5(str(path).encode()).hexdigest()[:16]
            import psycopg
            with psycopg.connect(url, autocommit=True) as c:
                c.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        if url:
            from app.db import PgConnection, pg_schema
            self.backend, self.path = "postgres", None
            self.db = PgConnection(url, schema=schema)
            self.db.executescript(pg_schema(SCHEMA))
            for table, cols in MIGRATIONS.items():
                have = self.db.columns(table)
                for name, kind in cols:
                    if name not in have:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}")
            return
        self.backend = "sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, kind in cols:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    # ------------------------------------------------------------ fleet (2b.3)

    def beat(self, bot: str, note: str | None = None) -> None:
        """This bot is alive (the head bot's watchdog reads it)."""
        self.db.execute("INSERT INTO heartbeats (bot, at, note) VALUES (?, ?, ?) ON CONFLICT (bot) DO UPDATE"
                        " SET at = excluded.at, note = excluded.note", (bot, _now(), note))
        self.db.commit()

    def heartbeats(self) -> list:
        return self.db.execute("SELECT * FROM heartbeats ORDER BY bot").fetchall()

    def set_fleet(self, key: str, value: str | None) -> None:
        self.db.execute("INSERT INTO fleet_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT (key)"
                        " DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at", (key, value, _now()))
        self.db.commit()

    def fleet(self, key: str) -> str | None:
        r = self.db.execute("SELECT value FROM fleet_settings WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None

    def global_pause(self) -> bool:
        """The head bot's pause for every bot (on top of each bot's own /pause)."""
        return (self.fleet("global_pause") or "") == "on"

    # ---------------------------------------------------------- fleet commands (2b.4)

    def add_command(self, command: str, by: str | None = None, note: str | None = None) -> int:
        """The head bot asks every bot to do something (e.g. "flatten"); each bot does it with its own keys."""
        cur = self.db.execute("INSERT INTO fleet_commands (command, created_at, created_by, note) VALUES (?, ?, ?, ?)",
                              (command, _now(), by, note))
        self.db.commit()
        return cur.lastrowid

    def pending_commands(self, bot: str, max_age_s: int = 120) -> list:
        """Commands this bot hasn't carried out yet. Only recent ones: a bot starting later never acts
        on an old command (the global pause still holds it back)."""
        since = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat(timespec="seconds")
        return self.db.execute(
            "SELECT c.* FROM fleet_commands c LEFT JOIN fleet_command_acks a ON a.command_id = c.id AND a.bot = ?"
            " WHERE a.command_id IS NULL AND c.created_at >= ? ORDER BY c.id", (bot, since)).fetchall()

    def ack_command(self, command_id: int, bot: str, result: str | None = None) -> None:
        self.db.execute("INSERT INTO fleet_command_acks (command_id, bot, at, result) VALUES (?, ?, ?, ?)"
                        " ON CONFLICT (command_id, bot) DO NOTHING", (command_id, bot, _now(), result))
        self.db.commit()

    def command_acks(self, command_id: int) -> list:
        return self.db.execute("SELECT * FROM fleet_command_acks WHERE command_id = ? ORDER BY bot",
                               (command_id,)).fetchall()

    def save_report(self, bot: str, day: str, text: str) -> None:
        """A bot's after-close summary, for the head bot to post (a rerun replaces it)."""
        self.db.execute("INSERT INTO daily_reports (bot, day, text, at) VALUES (?, ?, ?, ?) ON CONFLICT (bot, day)"
                        " DO UPDATE SET text = excluded.text, at = excluded.at", (bot, day, text, _now()))
        self.db.commit()

    def reports(self, day: str) -> list:
        return self.db.execute("SELECT * FROM daily_reports WHERE day = ? ORDER BY bot", (day,)).fetchall()

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

    def save_backtest(self, run_id: int, decisions: list) -> None:
        """Bulk-save a backtest run: every signal (with its plan), whether it was alerted, whether it
        was taken (as a 'took' response: the backtest approves every alert) and its outcome."""
        run = self.run(run_id)
        if run is None or run["source"] != "backtest":
            raise ValueError(f"run {run_id} is not a backtest run")
        now = _now()
        cur = self.db.cursor()
        for d in decisions:
            s, o = d.signal, d.signal.outcome or {}
            cur.execute(
                "INSERT INTO signals (run_id, strategy, source, date, symbol, status, reason, trigger_time,"
                " trigger_price, or_high, or_low, volume_x, entry, stop, target, target_r, risk_per_share, qty,"
                " max_loss, risk_verdict, risk_reasons, created_at)"
                " VALUES (?, ?, 'backtest', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, run["strategy"], s.day, s.symbol, s.status, s.reason or None, s.trigger_time,
                 s.trigger_price, s.or_high, s.or_low, s.volume_x, s.entry, s.stop, s.target, s.target_r,
                 s.risk_per_share, s.qty, s.max_loss,
                 ("PASS" if d.taken else "BLOCK") if d.alerted else None,
                 json.dumps([] if d.taken else [d.why]), now))
            sid = cur.lastrowid
            cur.execute("INSERT INTO alerts (signal_id, sent, held_reason, at) VALUES (?, ?, ?, ?)",
                        (sid, int(d.alerted), None if d.alerted else d.why, now))
            if d.taken:
                cur.execute("INSERT INTO responses (signal_id, action, user_id, at) VALUES (?, 'took', 'backtest', ?)",
                            (sid, now))
            if o.get("result"):
                cur.execute(
                    "INSERT INTO outcomes (signal_id, result, exit_price, exit_time, r_multiple, pnl_usd, method,"
                    " resolved_at, r_gross, cost_usd, mfe_r, mae_r, bars_held)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sid, o["result"], o.get("exit_price"), o.get("exit_time"), o.get("r_net"), o.get("pnl_usd"),
                     o.get("method", ""), now, o.get("r_gross"), o.get("cost_usd"), o.get("mfe_r"),
                     o.get("mae_r"), o.get("bars_held")))
        self.db.commit()

    def runs(self, *, strategy: str | None = None, source: str | None = None) -> list[sqlite3.Row]:
        where, args = [], []
        for col, val in (("strategy", strategy), ("source", source)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
        return self.db.execute(sql, args).fetchall()

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

    def save_outcome(self, signal_id: int, o: "Outcome") -> None:
        """Save an outcome from app.outcomes.resolve (R and $ already include costs)."""
        if self.signal(signal_id) is None:
            raise ValueError(f"no signal {signal_id}")
        self.db.execute(
            "INSERT INTO outcomes (signal_id, result, exit_price, exit_time, r_multiple, pnl_usd, method,"
            " resolved_at, r_gross, cost_usd, mfe_r, mae_r, bars_held)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (signal_id) DO UPDATE SET"
            " result = excluded.result, exit_price = excluded.exit_price, exit_time = excluded.exit_time,"
            " r_multiple = excluded.r_multiple, pnl_usd = excluded.pnl_usd, method = excluded.method,"
            " resolved_at = excluded.resolved_at, r_gross = excluded.r_gross, cost_usd = excluded.cost_usd,"
            " mfe_r = excluded.mfe_r, mae_r = excluded.mae_r, bars_held = excluded.bars_held",
            (signal_id, o.result, o.exit_price, o.exit_time, o.r_net, o.pnl_usd, o.method, _now(),
             o.r_gross, o.cost_usd, o.mfe_r, o.mae_r, o.bars_held))
        self.db.commit()

    # ---------------------------------------------------------------- orders (1b)

    def add_order(self, signal_id: int, client_order_id: str, symbol: str, qty: int, limit_price: float,
                  stop: float, target: float, *, broker_order_id: str | None = None,
                  status: str = "submitted") -> int:
        cur = self.db.execute(
            "INSERT INTO orders (signal_id, client_order_id, broker_order_id, symbol, qty, limit_price, stop,"
            " target, status, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (signal_id, client_order_id, broker_order_id, symbol, qty, limit_price, stop, target, status, _now()))
        self.db.commit()
        return cur.lastrowid

    def update_order(self, client_order_id: str, **fields) -> None:
        allowed = {"broker_order_id", "status", "filled_qty", "filled_price", "filled_at", "exit_reason",
                   "exit_price", "exited_at", "pnl_usd", "note", "stop_order_id", "target_order_id",
                   "entry_slippage", "exit_slippage", "stop", "target", "live_card_channel_id",
                   "live_card_message_id", "closed_card_message_id"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown order fields {bad}")
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(f"UPDATE orders SET {sets} WHERE client_order_id = ?",
                            (*fields.values(), client_order_id))
            self.db.commit()

    def order_for_signal(self, signal_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM orders WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
                               (signal_id,)).fetchone()

    def order(self, client_order_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)).fetchone()

    def open_orders(self, strategy: str | None = None) -> list[sqlite3.Row]:
        """Live paper orders still waiting to fill or in a trade (one bot's, when strategy is given:
        in the shared database every bot's orders sit side by side)."""
        if strategy is None:
            return self.db.execute("SELECT * FROM orders WHERE status IN ('submitted', 'partially_filled',"
                                   " 'filled') ORDER BY id").fetchall()
        return self.db.execute("SELECT o.* FROM orders o JOIN signals s ON s.id = o.signal_id WHERE s.strategy = ?"
                               " AND o.status IN ('submitted', 'partially_filled', 'filled') ORDER BY o.id",
                               (strategy,)).fetchall()

    def add_event(self, client_order_id: str, kind: str, old=None, new=None, note: str | None = None) -> None:
        self.db.execute("INSERT INTO trade_events (client_order_id, at, kind, old_value, new_value, note)"
                        " VALUES (?, ?, ?, ?, ?, ?)", (client_order_id, _now(), kind, old, new, note))
        self.db.commit()

    def events(self, client_order_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM trade_events WHERE client_order_id = ? ORDER BY id",
                               (client_order_id,)).fetchall()

    def order_by_any_id(self, oid: str) -> tuple[sqlite3.Row, str] | None:
        """An order row from Alpaca's ids: (row, "entry" | "stop" | "target")."""
        for col, part in (("client_order_id", "entry"), ("broker_order_id", "entry"),
                          ("stop_order_id", "stop"), ("target_order_id", "target")):
            row = self.db.execute(f"SELECT * FROM orders WHERE {col} = ?", (oid,)).fetchone()
            if row is not None:
                return row, part
        return None

    def alert_at(self, signal_id: int) -> str | None:
        a = self.alert(signal_id)
        return a["at"] if a else None

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


# ------------------------------------------------------------- one-time move (2b.3)

COPY_ORDER = ("runs", "signals", "alerts", "responses", "orders", "trade_events", "outcomes", "heartbeats",
              "fleet_settings")


def migrate_sqlite_to_postgres(sqlite_path: Path, pg: "TradeLog") -> dict | None:
    """Copy a bot's SQLite trade log into the (empty) shared Postgres, keeping every id, then keep
    the SQLite file as a backup (renamed). Does nothing if there's no file or Postgres already has
    runs. Returns {table: rows copied} when it copied."""
    if pg.backend != "postgres" or not sqlite_path.exists():
        return None
    if pg.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]:
        return None
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    copied = {}
    for table in COPY_ORDER:
        try:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
        except sqlite3.OperationalError:
            continue                                     # an older file without this table
        if not rows:
            copied[table] = 0
            continue
        cols = [c for c in rows[0].keys() if c in pg.db.columns(table)]
        marks = ", ".join("?" for _ in cols)
        for r in rows:
            pg.db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})", tuple(r[c] for c in cols))
        copied[table] = len(rows)
    for table in ID_SEQUENCED:
        pg.db.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                      f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")
    src.close()
    backup = sqlite_path.with_name(sqlite_path.name + ".moved-to-postgres")
    sqlite_path.rename(backup)
    for extra in ("-wal", "-shm"):
        side = sqlite_path.with_name(sqlite_path.name + extra)
        if side.exists():
            side.rename(backup.with_name(backup.name + extra))
    return copied


ID_SEQUENCED = ("runs", "signals", "alerts", "responses", "orders", "trade_events")
