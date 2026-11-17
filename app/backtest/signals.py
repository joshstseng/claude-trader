"""The signal engine: the live ORB rules applied to history.

For each market day and each stock on that day's focus list:
  entry   the skill's entry.evaluate (the same function trader-entry runs live) on the day's
          5-minute bars: the first bar after the opening range to CLOSE above the range high with
          enough volume, closing inside the scan window
  plan    the skill's exit.compute (stop and target) and size.size_trade (shares, refusals)
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
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Callable

from app import outcomes, skill
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


def _chart(symbol: str, bars: list[Bar]) -> dict:
    """Bars -> the chart shape the skill's entry.evaluate reads (as if from Yahoo, fully settled)."""
    return {"symbol": symbol, "meta": {}, "prev_close": None, "data_time": None,
            "bars": [{"t": int(b.start.astimezone(timezone.utc).timestamp()), "o": b.o, "h": b.h, "l": b.l,
                      "c": b.c, "v": int(b.v)} for b in bars]}


def signal_for(symbol: str, bars: list[Bar], session: Session, settings: dict, rules: dict, *,
               cost_pct: float, focus_rank: int = 0, outcome_bars: list[Bar] | None = None) -> BtSignal | None:
    """One stock, one day. None if it never triggered.
    `outcome_bars`: score the trade on different bars than the ones that decided it (e.g. decide
    on the free IEX feed, score on the whole market's bars, which is what a real fill would see)."""
    entry_mod, exit_mod, size_mod = skill.module("entry"), skill.module("exit"), skill.module("size")
    win = settings["scan_window"]
    check_at = session.at(dtime.fromisoformat(win["end"])) + timedelta(minutes=1)
    cfg = {"no_entries_before": rules.get("no_entries_before", "09:45"), "no_entries_after": win["end"]}
    res = entry_mod.evaluate(_chart(symbol, bars), check_at.astimezone(timezone.utc).replace(tzinfo=None),
                             setup="orb", or_minutes=settings["opening_range_minutes"],
                             interval=settings["interval"], min_volume_x=settings.get("min_volume_x"), cfg=cfg)
    if res["status"] != "triggered":
        return None
    trig, orng = res["trigger"], res["opening_range"]
    if trig["price"] < settings["focus_list"]["min_price"]:
        return None                      # the live scan's price floor (--min-price) at the check
    slots = {b["slot"] for b in res["_bars"]}
    if any(k not in slots for k in range(trig["bar_index"] + 1)):
        return None                      # a missing bar: the live scan would have skipped this chart

    sig = BtSignal(day=session.day.isoformat(), symbol=symbol, status="pass", trigger_time=trig["close_time"],
                   bar_index=trig["bar_index"], trigger_price=trig["price"], or_high=orng["high"],
                   or_low=orng["low"], volume_x=trig["volume_x"], pct_over=trig["pct_over"],
                   focus_rank=focus_rank)

    # stop and target: the skill's exit.compute
    try:
        stop_rule, stop_param = exit_mod.parse_stop(settings["exit"]["stop"])
        target_rule, target_param = exit_mod.parse_target(settings["exit"]["target"])
        atr = atr_n = None
        if stop_rule == "atr":
            upto = [{"h": b.h, "l": b.l, "c": b.c} for b in bars
                    if b.start < session.at(dtime.fromisoformat(trig["close_time"]))]
            atr, atr_n = exit_mod.atr_of(upto)
        plan = exit_mod.compute(trig["price"], stop_rule, stop_param, target_rule, target_param,
                                or_high=orng["high"], or_low=orng["low"], atr=atr, atr_bars=atr_n)
    except exit_mod.PlanError as e:
        sig.status, sig.reason = "refused", f"exit plan: {e}"
        return sig
    sig.entry, sig.stop, sig.target = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    sig.target_r, sig.risk_per_share = float(plan["target_r"]), float(plan["risk"])

    # shares: the skill's size.size_trade (max loss, position cap, max order, cash buffer)
    sizing = size_mod.size_trade({"symbol": symbol, "side": "buy", "entry": sig.entry, "stop": sig.stop,
                                  "target": sig.target, "date": sig.day, "setup": "orb"}, rules)
    sig.qty, sig.cost, sig.max_loss, sig.bound_by = sizing["qty"], sizing["cost"], sizing["max_loss"], sizing["bound_by"]
    if sizing["refusal"]:
        sig.status, sig.reason = "refused", f"budget: {sizing['refusal']}"
        return sig

    o = outcomes.resolve(entry=sig.entry, stop=sig.stop, target=sig.target,
                         entry_at=session.at(dtime.fromisoformat(sig.trigger_time)),
                         bars=outcome_bars if outcome_bars is not None else bars,
                         flat_by=flat_by_for(session, rules), qty=sig.qty, cost_pct=cost_pct)
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
