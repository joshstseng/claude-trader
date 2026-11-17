"""Takes one signal through the day-trader-skill scripts:

    entry -> exit -> time machine -> budget -> risk -> news

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
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app import paths
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
    entry: Path | None = None        # Yahoo chart JSON for the day (5m bars)
    timemachine: Path | None = None  # Yahoo chart JSON, ~60 days of 5m bars
    news: Path | None = None         # folder of saved headlines / filings


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
) -> SignalResult:
    """Run one symbol through the whole pipeline. Never raises for a step failure:
    the result's status and reason say what happened."""
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

    # 1. entry: has the ORB triggered?
    args = ["check", symbol, "--setup", "orb", "--interval", s["interval"],
            "--or-minutes", str(s["opening_range_minutes"]), "--json", "--write", *clock]
    if s.get("min_volume_x"):
        args += ["--min-volume-x", str(s["min_volume_x"])]
    if off.entry:
        args += ["--offline", str(off.entry)]
    e = step("entry", args)
    if e.data is None:
        result.reason = f"entry: {e.error}"
        return result
    if e.data.get("status") != "triggered":
        result.status = e.data.get("status") or "error"
        result.reason = e.data.get("reason", "")
        return result

    # 2. exit: stop and target
    x = step("exit", ["plan", "--stop", s["exit"]["stop"], "--target", s["exit"]["target"],
                      "--json", "--write", *clock])
    if not x.ok:
        result.status = "refused"
        result.reason = f"exit plan: {x.error or (x.data or {}).get('error', 'refused')}"
        return result

    # 3. time machine: odds (information only; a failure here doesn't stop the signal)
    if s.get("timemachine", {}).get("enabled", True):
        args = ["run", "--json", "--write", *clock]
        if off.timemachine:
            args += ["--offline", str(off.timemachine)]
        step("timemachine", args)

    # 4. budget: how many shares
    b = step("budget", ["--json", "--write", *clock])
    refusal = (b.data or {}).get("sizing", {}).get("refusal") if b.data else None
    if not b.ok or refusal or not (b.data or {}).get("orders"):
        result.status = "refused"
        result.reason = f"budget: {refusal or b.error or 'no order'}"
        return result

    # 5. risk: PASS / BLOCK against the rules, counting today's shared state
    r = step("risk", ["--json", "--state", str(day_state / "broker.json"), "--today", date, *clock])
    verdict = (result.risk or {}).get("verdict")
    if verdict == "PASS":
        result.status = "pass"
    elif verdict == "BLOCK":
        result.status = "blocked"
        result.reason = "; ".join((result.risk or {}).get("reasons", [])) or "blocked"
    else:
        result.reason = f"risk: {r.error or 'no verdict'}"

    # 6. news: headlines and filings for the alert (information only)
    if with_news:
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
