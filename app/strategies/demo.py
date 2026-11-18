"""A demo brain: VWAP reclaim (Step 2b.1). It exists to prove that a second strategy plugs into the
shared plumbing without touching the ORB bot's code. It is switched off and not meant for trading.

    watchlist    the same focus list as the ORB bot
    decide       after 10:00, the first completed 5-minute bar that CLOSES above the session's VWAP
                 (volume-weighted average price) after the bar before it closed below it;
                 stop = the session's low so far, target = 2R; shares via the skill's size_trade
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone

from app import engine, market, skill
from app.market import NY, Session
from app.strategies.base import Brain

BAR = timedelta(minutes=5)


class DemoBrain(Brain):
    id = "demo"
    tag = "DEMO"

    def check_times(self, session: Session) -> list[datetime]:
        return market.check_times(session, self.s)

    def watchlist_live(self, workdir):
        from app.strategies.orb import OrbBrain
        return OrbBrain(self.s).watchlist_live(workdir)

    def watchlist_history(self, day, store):
        from app.strategies.orb import OrbBrain
        return OrbBrain(self.s).watchlist_history(day, store)

    def decide(self, symbol, chart, session, now, rules, flat_by=None):
        exit_mod, size_mod = skill.module("exit"), skill.module("size")
        start = session.at(dtime(9, 30))
        win_start = session.at(dtime.fromisoformat(self.s["scan_window"]["start"]))
        win_end = session.at(dtime.fromisoformat(self.s["scan_window"]["end"]))
        bars = []
        for b in chart["bars"]:
            t = datetime.fromtimestamp(b["t"], timezone.utc).astimezone(NY)
            if t.date() == session.day and start <= t and t + BAR <= now and b["t"] % 300 == 0:
                bars.append((t, b))
        bars.sort(key=lambda x: x[0])
        res = {"symbol": symbol, "setup": "vwap", "side": "buy", "date": session.day.isoformat(), "interval": "5m",
               "or_minutes": 15, "status": "waiting", "reason": "", "level": None, "trigger": None,
               "opening_range": None, "_bars": [], "minutes_since": None}
        pv = vol = 0.0
        low = None
        prev_close = prev_vwap = None
        for i, (t, b) in enumerate(bars):
            typical = (b["h"] + b["l"] + b["c"]) / 3
            pv += typical * b["v"]
            vol += b["v"]
            vwap = pv / vol if vol else None
            low = b["l"] if low is None else min(low, b["l"])
            end = t + BAR
            if (vwap is not None and prev_vwap is not None and win_start <= end <= win_end
                    and prev_close < prev_vwap and b["c"] > vwap):
                res.update(status="triggered", reason=f"the {t:%-I:%M} bar closed back above VWAP",
                           level=round(vwap, 2),
                           opening_range={"high": round(max(x[1]["h"] for x in bars[:i + 1]), 2),
                                          "low": round(low, 2), "minutes": 15},
                           trigger={"time": end.strftime("%-I:%M %p"), "close_time": end.strftime("%H:%M"),
                                    "bar_start": t.strftime("%H:%M"), "bar_index": i, "price": round(b["c"], 2),
                                    "close": b["c"], "volume": b["v"], "volume_x": None,
                                    "pct_over": round((b["c"] / vwap - 1) * 100, 2)},
                           minutes_since=int((now - end).total_seconds() // 60))
                break
            prev_close, prev_vwap = b["c"], vwap
        if res["status"] != "triggered":
            if now >= win_end:
                res.update(status="expired", reason="no VWAP reclaim in the window")
            return engine.Decision(res["status"], res["reason"], res)
        trig = res["trigger"]
        if trig["price"] < self.s["focus_list"]["min_price"]:
            return engine.Decision("skipped", "under the price floor", res)
        try:
            target_rule, target_param = exit_mod.parse_target(self.s["exit"]["target"])
            c = exit_mod.compute(trig["price"], "price", exit_mod.D(str(res["opening_range"]["low"])),
                                 target_rule, target_param)
        except exit_mod.PlanError as e:
            return engine.Decision("refused", f"exit plan: {e}", res)
        plan = {"symbol": symbol, "side": "buy", "date": session.day.isoformat(), "setup": "vwap",
                "entry": float(c["entry"]), "entry_time": trig["time"], "entry_bar": trig["bar_index"],
                "interval": "5m", "opening_range": res["opening_range"], "stop": float(c["stop"]),
                "stop_rule": "price", "stop_label": "session low", "target": float(c["target"]), "target_r": float(c["target_r"]),
                "target_label": c["target_label"], "risk_per_share": float(c["risk"]), "reward_risk": float(c["reward_risk"]),
                "flat_by": (flat_by or dtime(15, 55)).strftime("%H:%M")}
        sizing = size_mod.size_trade(plan, rules)
        if sizing["refusal"]:
            return engine.Decision("refused", f"budget: {sizing['refusal']}", res, plan, sizing)
        return engine.Decision("planned", "", res, plan, sizing, size_mod.bracket_order(sizing))
