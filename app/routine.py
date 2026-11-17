"""The ORB bot's trading day: pre-market focus list, then a check every 5 minutes in the scan window.

Each check:
  1. the repo's fast ORB scan over the focus list (20 stocks a request) finds charts that closed
     above their opening range,
  2. each of those goes through the full pipeline (entry with the volume check, exit, time machine,
     budget, risk, news),
  3. a triggered breakout is logged as a signal, then sent to Discord or held back (with the reason).

A stock that is above its range but not yet triggered (e.g. the volume check failed) is checked
again next time. Every signal is logged whether it was alerted or not.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from app import market, paths, pipeline, tradelog
from app.strategies import Strategy

log = logging.getLogger(__name__)


class Alerter(Protocol):
    def send(self, signal_id: int, result: pipeline.SignalResult) -> tuple[int | None, int | None]:
        """Post the alert. Returns (channel_id, message_id)."""


class LogAlerter:
    """Until the Discord bot exists (1a.6): alerts go to the log."""

    def __init__(self):
        self.sent: list[tuple[int, pipeline.SignalResult]] = []

    def send(self, signal_id, result):
        p, o = result.plan or {}, result.order or {}
        log.info("[ORB] ALERT %s  entry %.2f at %s  stop %.2f  target %.2f  %s shares",
                 result.symbol, p.get("entry", 0), p.get("entry_time"), p.get("stop", 0),
                 p.get("target", 0), o.get("qty"))
        self.sent.append((signal_id, result))
        return None, None


def decide_alert(result: pipeline.SignalResult, *, sent_today: int, settings: dict,
                 paused: bool) -> tuple[bool, str | None]:
    """Pure. (send?, reason it was held back)."""
    al = settings["alerts"]
    if result.status != "pass":
        if al.get("require_risk_pass", True) or result.status != "blocked":
            return False, f"{result.status}: {result.reason}".rstrip(": ")
    minutes = (result.entry or {}).get("minutes_since")
    if minutes is not None and minutes > al.get("stale_after_minutes", 10):
        return False, f"stale: triggered {minutes} minutes before this check"
    if paused:
        return False, "bot paused"
    if sent_today >= al["max_per_day"]:
        return False, f"daily alert cap ({al['max_per_day']})"
    return True, None


@dataclass
class DayData:
    """Saved data for replaying a whole day without the network."""
    bars: Path                       # bundle {TICKER: chart} or folder, for the ORB scan
    entry_dir: Path                  # folder of <TICKER>.json, for entry.py
    timemachine_dir: Path | None = None   # optional <TICKER>.json(.gz) with ~60 days of bars
    news_dir: Path | None = None

    def __post_init__(self):
        # the scripts run inside each signal's folder, so every path must be absolute
        for f in ("bars", "entry_dir", "timemachine_dir", "news_dir"):
            v = getattr(self, f)
            if v is not None:
                setattr(self, f, Path(v).resolve())

    def offline_for(self, symbol: str) -> pipeline.Offline:
        tm = None
        if self.timemachine_dir:
            names = [f"{symbol}.json.gz", f"{symbol}.json"]
            names += sorted(p.name for p in self.timemachine_dir.glob(f"{symbol}-*.json*"))
            for name in names:
                if (self.timemachine_dir / name).exists():
                    tm = self.timemachine_dir / name
                    break
        return pipeline.Offline(entry=self.entry_dir, timemachine=tm, news=self.news_dir,
                                allow_network=False)


@dataclass
class TickReport:
    at: str
    candidates: list[str] = field(default_factory=list)
    signals: list[tuple[str, str]] = field(default_factory=list)   # (symbol, status)
    alerted: list[str] = field(default_factory=list)
    held: list[tuple[str, str]] = field(default_factory=list)      # (symbol, reason)
    note: str | None = None


class OrbDay:
    def __init__(self, strategy: Strategy, rules: dict, trade_log: tradelog.TradeLog, *,
                 source: str, day: str, alerter: Alerter, runs_root: Path = paths.RUNS_DIR,
                 day_data: DayData | None = None, sec_user_agent: str | None = None):
        if strategy.id != "orb":
            raise ValueError("OrbDay runs the ORB bot only")
        self.strategy, self.s, self.rules = strategy, strategy.settings, rules
        self.log, self.source, self.day = trade_log, source, day
        self.alerter, self.runs_root, self.day_data = alerter, runs_root, day_data
        self.sec_user_agent = sec_user_agent
        self._paused = False
        self.pause_source: Callable[[], bool] | None = None   # e.g. the app's /pause setting
        self.focus: list[str] = []
        self.checks = 0                   # checks run by this process today
        self.done: set[str] = set()       # signaled, expired or failed for good today
        self.signal_ids: dict[str, int] = {}
        self.workdir = runs_root / day / strategy.id
        # a live day resumes after a restart: same run, same daily cap, same "already handled" list,
        # so a redeploy mid-morning can't alert a stock twice or reset the cap. Replays start fresh.
        existing = trade_log.find_day_run(strategy.id, source, day) if source == "live" else None
        if existing:
            self.run_id = existing["id"]
            self.done = {r["symbol"] for r in trade_log.signals(run_id=self.run_id)}
            self.resumed = True
            log.info("[ORB] resuming today's run %s (%d signals so far)", self.run_id, len(self.done))
        else:
            self.run_id = trade_log.start_run(
                strategy.id, source, {"strategy": strategy.settings, "risk": rules},
                label=f"ORB {source} {day}", date_from=day, date_to=day)
            self.resumed = False

    @property
    def scanned_today(self) -> bool:
        """Did the bot check for breakouts today? (This process ran a check, or an earlier copy
        built today's focus list, which only happens on days the checks are scheduled.)"""
        return self.checks > 0 or (self.workdir / "focus_symbols.json").exists()

    @property
    def paused(self) -> bool:
        return self._paused or bool(self.pause_source and self.pause_source())

    @paused.setter
    def paused(self, value: bool) -> None:
        self._paused = bool(value)

    # ---------------------------------------------------------------- pre-market

    def premarket(self, focus: list[str] | None = None) -> list[str]:
        """Build (or take) the focus list for the day."""
        if focus is None:
            saved = self.workdir / "focus.json"
            if self.day_data:
                focus = market.offline_symbols(self.day_data.bars)
            elif saved.exists():                     # restarted today: reuse today's list
                focus = json.loads(saved.read_text())["symbols"]
                log.info("[ORB] reusing today's focus list (%d stocks)", len(focus))
            else:
                doc = market.build_focus_list(self.s["focus_list"], self.workdir / "focus.json")
                focus = doc["symbols"]
                log.info("[ORB] focus list: %d most traded + %d daily-scan hits (closes through %s, %ss)",
                         len(doc["top"]), len(doc["daily_hits"]), doc["closes_through"], doc["seconds"])
        self.focus = [s.upper() for s in focus]
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "focus_symbols.json").write_text(json.dumps(self.focus))
        return self.focus

    # --------------------------------------------------------------------- check

    def _orb_scan(self, symbols: list[str], now: str | None) -> tuple[list[dict], str | None]:
        """The repo's ORB scan. Returns (hits in trigger order, note if it couldn't run)."""
        folder = self.workdir / "_scan"
        (folder / "trader").mkdir(parents=True, exist_ok=True)
        (folder / "trader" / "config.json").write_text(json.dumps(self.rules))
        args = [sys.executable, str(market.SCAN_PY), "orb", "--symbols", ",".join(symbols),
                "--json", "--no-write", "--max-confirm", "0",
                "--or-minutes", str(self.s["opening_range_minutes"]),
                "--min-price", str(self.s["focus_list"]["min_price"])]
        if now:
            args += ["--now", now]
        if self.day_data:
            args += ["--offline", str(self.day_data.bars)]
        p = subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=600)
        try:
            doc = json.loads(p.stdout)
        except json.JSONDecodeError:
            return [], (p.stderr.strip() or p.stdout.strip() or "scan failed").splitlines()[-1]
        hits = sorted(doc.get("hits", []), key=lambda h: (h.get("bar_index", 0), h["symbol"]))  # trigger order
        return hits, None

    def tick(self, now: str | None = None) -> TickReport:
        """One check. `now` = "YYYY-MM-DD HH:MM" New York for replays, None for live."""
        self.checks += 1
        report = TickReport(at=now or datetime.now(market.NY).strftime("%Y-%m-%d %H:%M"))
        todo = [s for s in self.focus if s not in self.done]
        if not todo:
            report.note = "nothing left to check"
            return report
        hits, note = self._orb_scan(todo, now)
        if note:
            report.note = note
            log.warning("[ORB] scan at %s: %s", report.at, note)
            return report
        report.candidates = [h["symbol"] for h in hits]
        for h in hits:
            sym = h["symbol"]
            if sym in self.done:
                continue
            offline = self.day_data.offline_for(sym) if self.day_data else None

            def decide(res: pipeline.SignalResult) -> tuple[bool, str | None]:
                return decide_alert(res, settings=self.s, paused=self.paused, sent_today=self.log.alerts_sent(
                    strategy=self.strategy.id, date=self.day, source=self.source, run_id=self.run_id))

            # the slow time machine and news only run for a signal that will be alerted
            result = pipeline.run_signal(self.strategy, sym, self.rules, now=now, offline=offline,
                                         runs_root=self.runs_root, sec_user_agent=self.sec_user_agent,
                                         want_extras=lambda res: decide(res)[0])
            if not tradelog.is_signal(result):
                if result.status != "waiting":     # expired, no data, error: stop checking it today
                    self.done.add(sym)
                continue
            self.done.add(sym)
            sid = self.log.record_signal(self.run_id, result)
            self.signal_ids[sym] = sid
            report.signals.append((sym, result.status))
            send, reason = decide(result)
            if send:
                try:
                    channel_id, message_id = self.alerter.send(sid, result)
                except Exception as e:  # noqa: BLE001 - a failed post is logged, the day goes on
                    log.exception("[ORB] alert for %s failed", sym)
                    self.log.record_alert(sid, sent=False, held_reason=f"alert failed: {e}")
                    report.held.append((sym, f"alert failed: {e}"))
                    continue
                self.log.record_alert(sid, sent=True, channel_id=channel_id, message_id=message_id)
                report.alerted.append(sym)
            else:
                self.log.record_alert(sid, sent=False, held_reason=reason)
                report.held.append((sym, reason))
        log.info("[ORB] check %s: %d above range, %d new signals, %d alerted, %d held",
                 report.at, len(report.candidates), len(report.signals), len(report.alerted),
                 len(report.held))
        return report

    def finish(self) -> None:
        self.log.finish_run(self.run_id)
