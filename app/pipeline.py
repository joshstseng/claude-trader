"""Takes one signal through the ORB bot's steps:

    entry + stop/target + shares   app.engine.decide (in-process; the same code the backtest runs)
    risk                           the skill's check.py (the final gate)
    time machine, news             the skill's scripts, only when the signal will be alerted

Each signal runs in its own folder, runs/<date>/<strategy>/<TICKER>/, because the
scripts keep one trade at a time in fixed files (trader/entry.json, trader/plan.json).
The risk check's record of "what was placed today" is shared per day
(runs/<date>/state/), so daily limits count every signal, not just one.

The scripts are run as-is (never edited). Replay mode passes --now and --offline so a
past day can be rerun without the network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app import engine, market, paths, skill
from app.account import DayAccount
from app.strategies import Strategy

NY = ZoneInfo("America/New_York")
STEP_TIMEOUT_S = 180

SCRIPTS = {
    "entry": paths.SKILL_DIR / "trader-entry" / "entry.py",
    "exit": paths.SKILL_DIR / "trader-exit" / "exit.py",
    "timemachine": paths.SKILL_DIR / "trader-timemachine" / "timemachine.py",
    "budget": paths.SKILL_DIR / "trader-budget" / "size.py",
    "risk": paths.SKILL_DIR / "trader-risk" / "check.py",
    "news": paths.SKILL_DIR / "trader-news" / "news.py",
}


@dataclass
class Offline:
    """Saved data for replays. Each path is passed to that script's --offline flag."""
    entry: Path | None = None        # Yahoo chart JSON for the day (5m bars), or a folder of <TICKER>.json
    timemachine: Path | None = None  # Yahoo chart JSON, ~60 days of 5m bars
    news: Path | None = None         # folder of saved headlines / filings
    allow_network: bool = True       # False: a step without saved data is skipped, never fetched


@dataclass
class StepResult:
    name: str
    ok: bool
    returncode: int
    data: Any = None          # parsed JSON output
    error: str | None = None  # one plain line when it failed


@dataclass
class SignalResult:
    """What happened to one signal. `status` is one of:

    pass      triggered, planned, sized, and the risk check passed
    blocked   planned and sized, but the risk check blocked it
    refused   the exit plan or the budget refused it (e.g. stop too far for the max loss)
    waiting / expired / not_open / closed / no_data / ...   the entry did not trigger (entry's own status)
    error     a step failed in a way we did not expect
    """
    strategy: str
    symbol: str
    date: str
    folder: Path
    status: str
    reason: str = ""
    steps: dict[str, StepResult] = field(default_factory=dict)

    def data(self, step: str) -> Any:
        s = self.steps.get(step)
        return s.data if s else None

    @property
    def entry(self) -> dict | None:
        return self.data("entry")

    @property
    def plan(self) -> dict | None:
        return self.data("exit")

    @property
    def order(self) -> dict | None:
        b = self.data("budget")
        return (b.get("orders") or [None])[0] if b else None

    @property
    def risk(self) -> dict | None:
        r = self.data("risk")
        return (r.get("results") or [None])[0] if r else None


def _flat_by(session, rules: dict):
    from app.afterclose import flat_by_for
    return flat_by_for(session, rules)


def _today_ny() -> str:
    return datetime.now(NY).strftime("%Y-%m-%d")


def _run(name: str, args: list[str], cwd: Path) -> StepResult:
    cmd = [sys.executable, str(SCRIPTS[name]), *args]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=STEP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return StepResult(name, False, -1, error=f"{name} took longer than {STEP_TIMEOUT_S}s")
    (cwd / "logs").mkdir(exist_ok=True)
    (cwd / "logs" / f"{name}.out").write_text(p.stdout)
    if p.stderr:
        (cwd / "logs" / f"{name}.err").write_text(p.stderr)
    try:
        data = json.loads(p.stdout) if p.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    if data is None:
        msg = (p.stderr.strip() or p.stdout.strip() or "no output").splitlines()[-1]
        return StepResult(name, False, p.returncode, error=msg)
    return StepResult(name, p.returncode == 0, p.returncode, data=data)


def _write_config(folder: Path, risk_rules: dict, sec_user_agent: str | None) -> None:
    cfg = dict(risk_rules)
    if sec_user_agent:
        cfg["sec_user_agent"] = sec_user_agent
    (folder / "trader").mkdir(parents=True, exist_ok=True)
    (folder / "trader" / "config.json").write_text(json.dumps(cfg, indent=2))


def run_signal(
    strategy: Strategy,
    symbol: str,
    risk_rules: dict,
    *,
    now: str | None = None,          # "YYYY-MM-DD HH:MM" New York; None = live
    offline: Offline | None = None,
    runs_root: Path = paths.RUNS_DIR,
    sec_user_agent: str | None = None,
    with_news: bool = True,
    want_extras: Callable[[SignalResult], bool] | None = None,
    session: "market.Session | None" = None,
) -> SignalResult:
    """Run one symbol through the whole pipeline. Never raises for a step failure:
    the result's status and reason say what happened.

    The time machine and news are the slow steps and are information for the alert only, so they
    run last, after the risk check. `want_extras(result)` can skip them for a signal that won't be
    alerted (e.g. stale or over the daily cap)."""
    if strategy.id != "orb":
        raise ValueError(f"run_signal only knows the ORB bot so far, not {strategy.id!r}")
    s = strategy.settings
    off = offline or Offline()
    symbol = symbol.upper()
    date = now[:10] if now else _today_ny()

    folder = runs_root / date / strategy.id / symbol
    if folder.exists():
        shutil.rmtree(folder)   # a rerun of the same signal replaces the old record
    _write_config(folder, risk_rules, sec_user_agent)
    day_state = runs_root / date / "state"
    day_state.mkdir(parents=True, exist_ok=True)

    clock = ["--now", now] if now else []
    result = SignalResult(strategy.id, symbol, date, folder, status="error")

    def step(name: str, args: list[str]) -> StepResult:
        r = _run(name, args, folder)
        result.steps[name] = r
        return r

    # 1-3. entry, stop/target and shares: app.engine.decide, the same code the backtest runs
    entry_mod, size_mod = skill.module("entry"), skill.module("size")
    when = (datetime.strptime(now, "%Y-%m-%d %H:%M").replace(tzinfo=NY) if now else datetime.now(NY))
    sess = session or market.SkillCalendar().session(when.date()) or market.Session(when.date(), dtime(9, 30), dtime(16, 0))
    try:
        chart = entry_mod.get_chart(symbol, s["interval"], when.date(), offline=str(off.entry) if off.entry else None)
    except Exception as e:  # noqa: BLE001 - Yahoo down, unknown ticker, bad file: one plain line
        result.steps["entry"] = StepResult("entry", False, 1, error=str(e))
        result.reason = f"entry: {e}"
        return result
    d = engine.decide(symbol, chart, sess, when, s, risk_rules, flat_by=_flat_by(sess, risk_rules))
    utc = engine.to_utc_naive(when)
    entry_mod.write_json(str(folder / "trader" / "entry.json"), entry_mod.entry_doc(d.entry_res, utc))
    result.steps["entry"] = StepResult("entry", d.triggered, 0, data=entry_mod.public(d.entry_res))
    if not d.triggered:
        result.status, result.reason = d.entry_res.get("status") or "error", d.entry_res.get("reason", "")
        return result
    if d.status == "skipped":
        result.status, result.reason = "skipped", d.reason
        return result
    if d.plan:
        (folder / "trader" / "plan.json").write_text(json.dumps(d.plan, indent=2))
        result.steps["exit"] = StepResult("exit", True, 0, data=d.plan)
    if d.sizing:
        orders = [d.order] if d.order else []
        result.steps["budget"] = StepResult("budget", d.order is not None, 0,
                                            data={"sizing": d.sizing, "orders": orders, "notes": []})
        if d.order:
            size_mod.write_orders(str(folder / "trader" / "orders.json"), orders, risk_rules,
                                  source="trader/plan.json", now_utc=utc)
    if d.status == "refused":
        result.status, result.reason = "refused", d.reason
        return result

    # 4. risk: PASS / BLOCK against the rules, counting today's shared state
    acct = DayAccount.for_day(runs_root, date, risk_rules)      # today's simulated $5k account (1b.3)
    r = step("risk", ["--json", "--state", str(acct.broker_file), "--portfolio", str(acct.portfolio_file),
                      "--today", date, *clock])
    verdict = (result.risk or {}).get("verdict")
    if verdict == "PASS":
        result.status = "pass"
    elif verdict == "BLOCK":
        result.status = "blocked"
        result.reason = "; ".join((result.risk or {}).get("reasons", [])) or "blocked"
    else:
        result.reason = f"risk: {r.error or 'no verdict'}"

    if want_extras is not None and not want_extras(result):
        return result

    # 5. time machine: odds (information only; a failure here doesn't stop the signal)
    if s.get("timemachine", {}).get("enabled", True) and (off.timemachine or off.allow_network):
        args = ["run", "--json", "--write", *clock]
        if off.timemachine:
            args += ["--offline", str(off.timemachine)]
        step("timemachine", args)

    # 6. news: headlines and filings for the alert (information only)
    if with_news and (off.news or off.allow_network):
        args = ["--tickers", symbol, "--hours", "24", "--dry-run", "--json"]
        if now:
            args += ["--now", datetime.strptime(now, "%Y-%m-%d %H:%M").replace(tzinfo=NY).isoformat()]
        if off.news:
            args += ["--offline", str(off.news)]
        if sec_user_agent:
            args += ["--user-agent", sec_user_agent]
        else:
            args += ["--no-sec"]
        step("news", args)

    return result
