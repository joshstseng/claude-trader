"""Step 1b.1: would the free real-time feed (Alpaca IEX) make the same decisions as the whole
market's data (SIP, what the backtest uses)?

For each day and focus stock, the signal engine runs twice: on SIP bars and on IEX bars. IEX-driven
trades are scored on SIP bars (the real market a fill would see). Reported: how often the two agree,
how often IEX is missing a 5-minute bar (no IEX trade in it), price differences, and the backtest
results for both.
"""

from __future__ import annotations

import json
import statistics as st
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, time as dtime

from app.backtest import data, report, signals
from app.backtest.select import Rules, select


@dataclass
class FeedComparison:
    days: int = 0
    stock_days: int = 0
    iex_missing_bar: int = 0                 # stock-days where IEX lacks a 9:30–11:30 bar
    agree: Counter = field(default_factory=Counter)
    price_diff: list[float] = field(default_factory=list)   # |IEX close - SIP close| / SIP, same trigger bar
    sip: list = field(default_factory=list)  # BtSignals decided on SIP
    iex: list = field(default_factory=list)  # BtSignals decided on IEX, scored on SIP


def compare(start: date, end: date, settings: dict, rules: dict, *, cost_pct: float, progress=print) -> FeedComparison:
    out = FeedComparison()
    sessions = data.calendar(start, end)
    for k, s in enumerate(sessions, 1):
        focus = json.loads((data.FOCUS_DIR / f"{s.day}.json").read_text())["symbols"]
        sip = data.day_bars(s.day, focus, fetch=False)
        iex = data.day_bars(s.day, focus, feed="iex")
        out.days += 1
        day_sip, day_iex = [], []
        for rank, sym in enumerate(focus):
            if sym not in sip:
                continue
            out.stock_days += 1
            ib = iex.get(sym, [])
            window = {b.start.strftime("%H:%M") for b in ib if b.start.time() < dtime(11, 30)}
            if len(window) < 24:                       # 9:30 .. 11:25 = 24 bars
                out.iex_missing_bar += 1
            a = signals.signal_for(sym, sip[sym], s, settings, rules, cost_pct=cost_pct, focus_rank=rank)
            b = signals.signal_for(sym, ib, s, settings, rules, cost_pct=cost_pct, focus_rank=rank,
                                   outcome_bars=sip[sym]) if ib else None
            if a and b:
                out.agree["same trigger" if a.trigger_time == b.trigger_time else "both, different time"] += 1
                if a.trigger_time == b.trigger_time:
                    out.price_diff.append(abs(b.trigger_price - a.trigger_price) / a.trigger_price)
            elif a:
                out.agree["only full market (IEX missed it)"] += 1
            elif b:
                out.agree["only IEX (extra signal)"] += 1
            if a:
                day_sip.append(a)
            if b:
                day_iex.append(b)
        for lst, dst in ((day_sip, out.sip), (day_iex, out.iex)):
            lst.sort(key=lambda x: (x.bar_index, x.symbol))
            dst.extend(lst)
        if progress and (k % 10 == 0 or k == len(sessions)):
            progress(f"feeds: {k}/{len(sessions)} days")
    return out


def summary(c: FeedComparison, settings: dict, risk: dict) -> str:
    rules = Rules.from_settings(settings, risk, cash_limit=True)
    any_sig = sum(c.agree.values())
    same = c.agree["same trigger"]
    lines = [f"**{c.days} days, {c.stock_days:,} stock-days**",
             f"- Signals from either feed: {any_sig:,}; **same trigger bar on both: {same:,} ({same / any_sig * 100:.0f}%)**"]
    for k in ("both, different time", "only full market (IEX missed it)", "only IEX (extra signal)"):
        lines.append(f"- {k}: {c.agree[k]:,} ({c.agree[k] / any_sig * 100:.0f}%)")
    lines.append(f"- IEX missing at least one 9:30–11:30 bar: {c.iex_missing_bar / c.stock_days * 100:.1f}% of stock-days")
    if c.price_diff:
        pd = sorted(c.price_diff)
        lines.append(f"- Trigger price, same bar: median difference {st.median(pd) * 100:.3f}%, "
                     f"95% within {pd[int(.95 * len(pd))] * 100:.3f}%")
    lines.append("")
    lines.append("| Decided on | Trades (as traded) | Avg per trade | Total | Every signal | Signals |")
    lines.append("|---|---|---|---|---|---|")
    for name, sigs in (("Full market (SIP)", c.sip), ("IEX only (free real-time)", c.iex)):
        traded = [d.signal for d in select(sigs, rules) if d.taken]
        m = report.metrics(traded)
        e = report.metrics([x for x in sigs if x.status == "pass"])
        if m.get("trades"):
            lines.append(f"| {name} | {m['trades']} | {m['avg_r']:+.3f}R | ${m['total_usd']:+,.0f} | "
                         f"{e['avg_r']:+.3f}R | {e['trades']:,} |")
    return "\n".join(lines)
