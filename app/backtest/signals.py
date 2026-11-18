"""The signal engine: a strategy's live rules applied to history (ORB by default).

For each market day and each stock on that day's focus list:
  decide  the strategy's brain; for ORB app.engine.decide, the SAME function the live bot calls (the skill's entry.evaluate,
          exit.compute and size.size_trade, plus the live scan's filters), at the scan window's
          last check
  result  app.outcomes.resolve (target / stop / flat at 3:55), after costs

Differences from the live bot, on purpose:
  - every signal is acted on right when its bar closes (the live bot checks ~1 minute later)
  - the per-trade risk check is covered by the sizing refusals; the daily limits (trades per day,
    daily loss) are applied afterwards, in the selection step (2.4)
  - like the live scan, a stock with a missing 5-minute bar between 9:30 and the trigger is skipped
"""

from __future__ import annotations

import time as _time
from dataclasses import asdict, dataclass, field
from datetime import time as dtime
from typing import Callable

from app import engine, outcomes
from app.strategies import brain_for
from app.afterclose import flat_by_for
from app.market import Session
from app.outcomes import NY, Bar


@dataclass
class BtSignal:
    day: str
    symbol: str
    status: str                      # pass / refused
    reason: str = ""
    trigger_time: str = ""           # bar close, "HH:MM" New York
    bar_index: int = 0               # 5-minute slot of the trigger bar (3 = 9:45 bar)
    trigger_price: float = 0.0
    or_high: float = 0.0
    or_low: float = 0.0
    volume_x: float | None = None
    pct_over: float | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    target_r: float | None = None
    risk_per_share: float | None = None
    qty: int = 0
    cost: float | None = None        # entry x shares
    max_loss: float | None = None
    bound_by: str = ""
    focus_rank: int = 0              # position on the focus list (0 = most traded)
    outcome: dict = field(default_factory=dict)   # app.outcomes.Outcome as a dict (pass only)

    def as_dict(self) -> dict:
        return asdict(self)


def signal_for(symbol: str, bars: list[Bar], session: Session, settings: dict, rules: dict, *,
               cost_pct: float, focus_rank: int = 0, outcome_bars: list[Bar] | None = None) -> BtSignal | None:
    """One stock, one day. None if it never triggered (or was skipped by the scan's filters).
    The decision is the strategy's brain (for ORB: app.engine.decide), the same function the live
    bot calls, run at the brain's last check of the day. `outcome_bars`: score the trade on different bars than the ones that
    decided it (e.g. decide on the free IEX feed, score on the whole market's bars)."""
    flat_by = flat_by_for(session, rules)
    brain = brain_for(settings)
    d = brain.decide(symbol, engine.chart_from_bars(symbol, bars), session,
                     brain.backtest_check_time(session), rules, flat_by=flat_by)
    if not d.triggered or d.status == "skipped":
        return None
    trig, orng = d.entry_res["trigger"], d.entry_res["opening_range"]
    sig = BtSignal(day=session.day.isoformat(), symbol=symbol, status="pass", trigger_time=trig["close_time"],
                   bar_index=trig["bar_index"], trigger_price=trig["price"], or_high=orng["high"],
                   or_low=orng["low"], volume_x=trig["volume_x"], pct_over=trig["pct_over"],
                   focus_rank=focus_rank)
    if d.plan:
        sig.entry, sig.stop, sig.target = d.plan["entry"], d.plan["stop"], d.plan["target"]
        sig.target_r, sig.risk_per_share = d.plan["target_r"], d.plan["risk_per_share"]
    if d.sizing:
        s = d.sizing
        sig.qty, sig.cost, sig.max_loss, sig.bound_by = s["qty"], s["cost"], s["max_loss"], s["bound_by"]
    if d.status == "refused":
        sig.status, sig.reason = "refused", d.reason
        return sig
    o = outcomes.resolve(entry=sig.entry, stop=sig.stop, target=sig.target,
                         entry_at=session.at(dtime.fromisoformat(sig.trigger_time)),
                         bars=outcome_bars if outcome_bars is not None else bars,
                         flat_by=flat_by, qty=sig.qty, cost_pct=cost_pct)
    sig.outcome = o.as_dict()
    return sig


def generate(sessions: list[Session], focus_of: Callable[[Session], list[str]],
             bars_of: Callable[[Session, list[str]], dict[str, list[Bar]]], settings: dict, rules: dict, *,
             cost_pct: float, progress: Callable[[str], None] | None = None) -> list[BtSignal]:
    """Every signal over a range of days, in time order."""
    out: list[BtSignal] = []
    t0 = _time.time()
    for k, s in enumerate(sessions, 1):
        focus = focus_of(s)
        bars = bars_of(s, focus)
        day = []
        for rank, sym in enumerate(focus):
            if sym in bars:
                sig = signal_for(sym, bars[sym], s, settings, rules, cost_pct=cost_pct, focus_rank=rank)
                if sig:
                    day.append(sig)
        day.sort(key=lambda x: (x.bar_index, x.symbol))   # same order the live bot handles them in
        out.extend(day)
        if progress and (k % 50 == 0 or k == len(sessions)):
            progress(f"signals: {k}/{len(sessions)} days, {len(out)} signals, {_time.time() - t0:.0f}s")
    return out
