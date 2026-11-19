"""Real paper trades vs the backtest's version of the same trades (Step 1b.8).

Every live signal gets the backtest's result at 4:15 PM (app.outcomes, before costs: `r_gross` and
the exit price). For each paper trade we also have the real fills. So:

    cost per share = backtest P&L per share (no costs) - real P&L per share

That's exactly what the backtest must subtract to match reality, and it converts straight into the
backtest's setting: pct_per_side = cost per share / (entry + exit). Entry slippage (fill vs the
plan's entry), stop slippage, and any difference in how the trade played out are all inside it.

Also tracked: the fill rate (limit entries that never filled) and what those missed trades would
have done, since missing mostly winners is a hidden cost too.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict
from datetime import datetime

from app import tradelog

ICON = {"target": "✅", "stop": "❌", "flat": "➖", "flatten": "🛑"}


def _usd(x: float, cents: bool = True) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.{2 if cents else 0}f}"


def _r(x: float) -> str:
    return f"{x:+.2f}R".replace("-", "−")


def paper_trades(trade_log: tradelog.TradeLog, day: str | None = None) -> list[dict]:
    """Every approved paper order (live), with its plan, real fills and the backtest's result."""
    sql = ("SELECT o.*, s.date AS day, s.entry AS plan_entry, s.stop AS plan_stop, s.target AS plan_target,"
           " s.trigger_time, oc.result AS bt_result, oc.exit_price AS bt_exit, oc.r_gross AS bt_r"
           " FROM orders o JOIN signals s ON s.id = o.signal_id LEFT JOIN outcomes oc ON oc.signal_id = s.id"
           " WHERE s.source = 'live' AND s.strategy = ?" + (" AND s.date = ?" if day else "") + " ORDER BY o.id")
    from app.strategies import active_id
    rows = trade_log.db.execute(sql, (active_id(), day) if day else (active_id(),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        risk = (d["plan_entry"] or 0) - (d["plan_stop"] or 0)
        d["closed"] = d["status"] == "closed" and d["exit_price"] is not None and d["filled_price"] is not None
        d["missed"] = d["status"] in ("cancelled", "rejected") and not d["filled_qty"]
        if d["closed"]:
            real_ps = d["exit_price"] - d["filled_price"]
            d["real_r"] = real_ps / risk if risk else None
            if d["bt_exit"] is not None:
                bt_ps = d["bt_exit"] - d["plan_entry"]
                d["cost_ps"] = bt_ps - real_ps
                d["cost_pct_side"] = d["cost_ps"] / (d["filled_price"] + d["exit_price"])
                d["cost_r"] = d["cost_ps"] / risk if risk else None
        out.append(d)
    return out


def measured(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["closed"]]
    with_bt = [t for t in closed if t.get("cost_ps") is not None]
    placed = [t for t in trades if t["status"] != "rejected"]
    missed = [t for t in trades if t["missed"]]
    m = {"orders": len(placed), "filled": sum(1 for t in placed if t["filled_qty"]), "closed": len(closed),
         "missed": len(missed), "compared": len(with_bt)}
    m["fill_rate"] = m["filled"] / m["orders"] if m["orders"] else None
    if closed:
        slips = [t["entry_slippage"] for t in closed if t["entry_slippage"] is not None]
        m["entry_slip_ps"] = st.mean(slips) if slips else None
        m["entry_slip_pct"] = st.mean(t["entry_slippage"] / t["plan_entry"] for t in closed
                                      if t["entry_slippage"] is not None) if slips else None
        stops = [t["exit_slippage"] for t in closed if t["exit_reason"] == "stop" and t["exit_slippage"] is not None]
        m["stop_slip_ps"] = st.mean(stops) if stops else None
    if with_bt:
        m["cost_r"] = st.mean(t["cost_r"] for t in with_bt if t["cost_r"] is not None)
        m["cost_pct_side"] = st.mean(t["cost_pct_side"] for t in with_bt)
    if missed:
        bt = [t["bt_r"] for t in missed if t["bt_r"] is not None]
        m["missed_bt_r"] = st.mean(bt) if bt else None
    return m


def running(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["closed"]]
    by_day = defaultdict(float)
    for t in closed:
        by_day[t["day"]] += t["pnl_usd"] or 0
    return {"trades": len(closed), "wins": sum(1 for t in closed if (t["pnl_usd"] or 0) > 0),
            "total": sum(t["pnl_usd"] or 0 for t in closed), "days": dict(sorted(by_day.items())),
            "avg_r": st.mean(t["real_r"] for t in closed if t.get("real_r") is not None) if closed else None}


def costs_line(m: dict, assumed_pct: float) -> str | None:
    if not m["orders"]:
        return None
    parts = [f"fill rate {m['filled']}/{m['orders']}"]
    if m.get("entry_slip_ps") is not None:
        parts.append(f"entry slippage {_usd(m['entry_slip_ps'])}/sh ({m['entry_slip_pct'] * 100:+.3f}%)")
    if m.get("stop_slip_ps") is not None:
        parts.append(f"stop slippage {_usd(m['stop_slip_ps'])}/sh")
    if m.get("cost_pct_side") is not None:
        parts.append(f"**real cost vs backtest: {m['cost_pct_side'] * 100:.3f}%/side "
                     f"({_r(-m['cost_r'])} a trade)** · backtest assumes {assumed_pct * 100:.2f}%")
    if m.get("missed_bt_r") is not None:
        parts.append(f"missed entries would have averaged {_r(m['missed_bt_r'])}")
    return "💸 Costs: " + " · ".join(parts)


def day_section(trade_log: tradelog.TradeLog, day: str, assumed_pct: float) -> str | None:
    """The daily summary's paper-trading part: today's real trades, costs, and the running total."""
    today = paper_trades(trade_log, day)
    if not today:
        return None
    lines = ["**Paper trades (real fills):**"]
    for t in today:
        if t["closed"]:
            icon = ICON.get(t["exit_reason"], "•")
            vs = (f" · backtest said {ICON.get(t['bt_result'], '?')} {_r(t['bt_r'])}" if t["bt_r"] is not None else "")
            lines.append(f"{icon} **{t['symbol']}** {t['filled_qty']} sh: in ${t['filled_price']:,.2f} → out "
                         f"${t['exit_price']:,.2f} ({t['exit_reason']}) · **{_usd(t['pnl_usd'] or 0)}** "
                         f"{_r(t['real_r'] or 0)}{vs}")
        elif t["missed"]:
            bt = f" (backtest: {ICON.get(t['bt_result'], '?')} {_r(t['bt_r'])})" if t["bt_r"] is not None else ""
            lines.append(f"⌛ **{t['symbol']}**: limit never filled{bt}")
        else:
            lines.append(f"• **{t['symbol']}**: {t['status']}")
    run = running(paper_trades(trade_log))
    today_pnl = sum(t["pnl_usd"] or 0 for t in today if t["closed"])
    lines.append(f"Today **{_usd(today_pnl)}** · all-time paper P&L **{_usd(run['total'])}** over "
                 f"{run['trades']} trades ({run['wins']} winner{'' if run['wins'] == 1 else 's'})")
    c = costs_line(measured(today), assumed_pct)
    if c:
        lines.append(c)
    return "\n".join(lines)


def pnl_text(trade_log: tradelog.TradeLog, assumed_pct: float) -> str:
    """/pnl: the running total, recent days, and costs measured so far."""
    trades = paper_trades(trade_log)
    run = running(trades)
    if not run["trades"] and not trades:
        return "No paper trades yet. Approve an alert to place one."
    lines = [f"**ORB paper trading, all time:** {run['trades']} closed trades · {run['wins']} winner{'' if run['wins'] == 1 else 's'} · "
             f"**{_usd(run['total'])}**" + (f" · avg {_r(run['avg_r'])} a trade" if run["avg_r"] is not None else "")]
    for d, v in list(run["days"].items())[-10:]:
        lines.append(f"`{datetime.strptime(d, '%Y-%m-%d'):%a %b %d}` {_usd(v)}")
    m = measured(trades)
    c = costs_line(m, assumed_pct)
    if c:
        lines.append(c)
    if m.get("compared", 0) < 20:
        lines.append(f"-# {m.get('compared', 0)} of ~20 trades needed before the measured cost replaces the backtest's assumption")
    return "\n".join(lines)
