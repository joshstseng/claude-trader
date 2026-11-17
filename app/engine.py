"""The ORB bot's decision engine, shared by the live bot and the backtest (Step 1b.2).

One function, `decide`, turns a stock's chart at a moment in time into: no trigger yet / skipped /
refused / a full plan with a share count. It only calls day-trader-skill's own functions:

    entry.evaluate    has the opening range broken? (first 5-min CLOSE above the high, enough volume)
    exit.compute      stop and target
    size.size_trade   shares (max loss, position cap, max order, cash) and refusals

plus the two filters the live ORB scan applies: the price floor at the check, and skipping a chart
with a missing 5-minute bar before the trigger. The live bot feeds it Yahoo charts at each check;
the backtest feeds it full-market bars at the end of the scan window. Same code, same answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone

from app import skill
from app.market import Session


@dataclass
class Decision:
    status: str               # triggered / waiting / expired / no-data / ... / skipped / refused / planned
    reason: str
    entry_res: dict           # entry.evaluate's result (with "_bars")
    plan: dict | None = None  # trader-exit's plan.json shape
    sizing: dict | None = None
    order: dict | None = None  # the bracket order (Alpaca place_stock_order fields)

    @property
    def triggered(self) -> bool:
        return self.entry_res.get("status") == "triggered"


def to_utc_naive(t: datetime) -> datetime:
    """The skill's clock: naive UTC."""
    return t.astimezone(timezone.utc).replace(tzinfo=None)


def decide(symbol: str, chart: dict, session: Session, now: datetime, settings: dict, rules: dict,
           flat_by: dtime | None = None) -> Decision:
    """`chart` in the skill's shape ({symbol, meta, bars: [{t, o, h, l, c, v}], data_time}),
    `now` = the moment of the check (timezone-aware)."""
    entry_mod, exit_mod, size_mod = skill.module("entry"), skill.module("exit"), skill.module("size")
    win = settings["scan_window"]
    cfg = {"no_entries_before": rules.get("no_entries_before", "09:45"), "no_entries_after": win["end"]}
    res = entry_mod.evaluate(chart, to_utc_naive(now), setup="orb", or_minutes=settings["opening_range_minutes"],
                             interval=settings["interval"], min_volume_x=settings.get("min_volume_x"), cfg=cfg)
    if res["status"] != "triggered":
        return Decision(res["status"], res.get("reason", ""), res)
    trig, orng = res["trigger"], res["opening_range"]

    # the live ORB scan's filters
    if trig["price"] < settings["focus_list"]["min_price"]:
        return Decision("skipped", f"under the ${settings['focus_list']['min_price']} price floor", res)
    slots = {b["slot"] for b in res["_bars"]}
    if any(k not in slots for k in range(trig["bar_index"] + 1)):
        return Decision("skipped", "a 5-minute bar is missing before the trigger", res)

    # stop and target
    try:
        stop_rule, stop_param = exit_mod.parse_stop(settings["exit"]["stop"])
        target_rule, target_param = exit_mod.parse_target(settings["exit"]["target"])
        atr = atr_n = None
        if stop_rule == "atr":
            end = session.at(dtime.fromisoformat(trig["close_time"]))
            upto = [{"h": b["h"], "l": b["l"], "c": b["c"]} for b in res["_bars"] if b["end"] <= end.replace(tzinfo=None)]
            atr, atr_n = exit_mod.atr_of(upto)
        c = exit_mod.compute(trig["price"], stop_rule, stop_param, target_rule, target_param,
                             or_high=orng["high"], or_low=orng["low"], atr=atr, atr_bars=atr_n)
    except exit_mod.PlanError as e:
        return Decision("refused", f"exit plan: {e}", res)
    flat = (flat_by or dtime.fromisoformat(rules.get("flat_by", "15:55"))).strftime("%H:%M")
    plan = {"created_by": "trader-exit", "symbol": symbol, "side": "buy", "date": session.day.isoformat(),
            "setup": "orb", "entry": float(c["entry"]), "entry_time": trig["time"], "entry_bar": trig["bar_index"],
            "interval": settings["interval"],
            "opening_range": {"high": orng["high"], "low": orng["low"], "minutes": orng["minutes"]},
            "stop": float(c["stop"]), "stop_rule": stop_rule, "stop_label": c["stop_label"],
            "target": float(c["target"]), "target_r": float(c["target_r"]), "target_label": c["target_label"],
            "risk_per_share": float(c["risk"]), "reward_risk": float(c["reward_risk"]), "flat_by": flat,
            "stop_detail": c["stop_detail"], "created_at": to_utc_naive(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": exit_mod.NOTE}
    if atr is not None:
        plan["atr"], plan["atr_bars"] = round(atr, 4), atr_n

    # shares
    sizing = size_mod.size_trade(plan, rules)
    if sizing["refusal"]:
        return Decision("refused", f"budget: {sizing['refusal']}", res, plan, sizing)
    return Decision("planned", "", res, plan, sizing, size_mod.bracket_order(sizing))


def chart_from_bars(symbol: str, bars) -> dict:
    """app.outcomes.Bar list -> the skill's chart shape, fully settled (history)."""
    return {"symbol": symbol, "meta": {}, "prev_close": None, "data_time": None,
            "bars": [{"t": int(b.start.astimezone(timezone.utc).timestamp()), "o": b.o, "h": b.h, "l": b.l,
                      "c": b.c, "v": int(b.v)} for b in bars]}


def window_end_check(session: Session, settings: dict) -> datetime:
    """The last live check of the day: 1 minute after the scan window's last bar closes."""
    return session.at(dtime.fromisoformat(settings["scan_window"]["end"])) + timedelta(minutes=1)
