"""Uri's weekly "still matching the backtest?" check (paper phase, item 2). Pure functions over the daily records that
Swing (daily:swing:<day>) and Bumi (daily:bumi:<day>) publish; app/head.py posts the result on the week's last session.

Go-live gates (agreed 2026-11-25):
    Swing   6+ weeks of paper, 30+ trades, fills within about 1 bp of the model, always flat after the close
    Bumi    3+ real rebalances (2-3 months), opening fills within about 10 bp (0.1%) of the official open
"""
from __future__ import annotations

import json
from datetime import date

SWING_WEEKS, SWING_TRADES, SWING_SLIP_BP = 6, 30, 1.0
BUMI_REBALANCES, BUMI_SLIP_BP = 3, 10.0


def records(pairs: list[tuple[str, str]]) -> list[dict]:
    out = []
    for _, v in pairs:
        try:
            out.append(json.loads(v))
        except ValueError:
            pass
    return sorted(out, key=lambda r: r["day"])


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def _slips(rs: list[dict]) -> list[float]:
    return [f["slip_bp"] for r in rs for f in r.get("fills", []) if f.get("slip_bp") is not None]


def _avg(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def swing_section(week: list[dict], everything: list[dict]) -> tuple[str, str, list[str]]:
    """(headline lines, thread details, flags)."""
    live = [r for r in week if not r.get("off")]
    flags = []
    p, m = sum(r["paper_pnl"] for r in week), sum(r["model_pnl"] for r in week)
    pt, mt = sum(r["paper_trades"] for r in week), sum(r["model_trades"] for r in week)
    slip = _avg(_slips(week))
    if slip is not None and slip > 1.5 * SWING_SLIP_BP:
        flags.append(f"fills averaged {slip:+.1f} bp worse than the model")
    if any(r.get("flat_after_close") is False for r in week):
        flags.append("not flat after the close on " + ", ".join(r["day"] for r in week if r.get("flat_after_close") is False))
    if abs(pt - mt) > 1:
        flags.append(f"{pt} paper trades vs {mt} in the model")
    halts = [f"{r['day']}: {r['halt_why']}" for r in week if r.get("halt_why")]
    if halts:
        flags.append("safety net fired (" + "; ".join(halts) + ")")
    weeks = len({date.fromisoformat(r["day"]).isocalendar()[:2] for r in everything if not r.get("off")})
    trades = sum(r["paper_trades"] for r in everything)
    all_slip = _avg(_slips(everything))
    ap, am = sum(r["paper_pnl"] for r in everything), sum(r["model_pnl"] for r in everything)
    head = [f"**Swing** · {'⚠️ needs a look' if flags else '✅ on track'}",
            f"  {pt} trade{'' if pt == 1 else 's'} (model {mt}) · paper **{_usd(p)}** vs model {_usd(m)}"
            + (f" · fills {slip:+.1f} bp vs model" if slip is not None else ""),
            f"  Go-live: week {weeks} of {SWING_WEEKS} · {trades} of {SWING_TRADES} trades"
            + (f" · fills {all_slip:+.1f} bp (gate ≤ {SWING_SLIP_BP:.0f})" if all_slip is not None else "")]
    rows = [f"{r['day']}: " + ("off (" + r["off"] + ")" if r.get("off") else
            f"paper {_usd(r['paper_pnl'])} ({r['paper_trades']}) · model {_usd(r['model_pnl'])} ({r['model_trades']}) · "
            f"v1 {_usd(r['v1_pnl'])}" + (f" · fills {_avg(_slips([r])):+.1f} bp" if _slips([r]) else "")
            + (" · ⚠️ not flat" if r.get("flat_after_close") is False else "") + (f" · 🛑 {r['halt_why']}" if r.get("halt_why") else ""))
            for r in week]
    detail = ("Each day: paper P&L (closed trades) vs the v1.1 model, the v1 baseline, and the average fill vs the model's "
              "price (positive = paid more).\n" + "\n".join(rows) + f"\n\nSince paper started: paper {_usd(ap)} vs model {_usd(am)} · "
              f"{trades} trades over {weeks} week{'' if weeks == 1 else 's'}." + (f"\n⚠️ " + "\n⚠️ ".join(flags) if flags else ""))
    return "\n".join(head), detail, flags


def bumi_section(week: list[dict], everything: list[dict], sessions: int) -> tuple[str, str, list[str]]:
    flags = []
    fills = [f for r in week for f in r.get("fills", [])]
    slip = _avg(_slips(week))
    if slip is not None and slip > BUMI_SLIP_BP:
        flags.append(f"opening fills averaged {slip:+.1f} bp worse than the official open")
    if any(r.get("filled_all") is False for r in week):
        flags.append("some opening orders didn't fill in full")
    if len(week) < sessions:
        flags.append(f"plans on {len(week)} of {sessions} market days")
    rebal = sum(1 for r in everything if r.get("fills"))
    all_slip = _avg(_slips(everything))
    last = week[-1] if week else None
    if fills:
        what = f"{len(fills)} fill{'' if len(fills) == 1 else 's'}" + (f" · {slip:+.1f} bp vs the open" if slip is not None else "")
    else:
        what = "no trades" + (f" · VIX {last['vix']:.1f}, {'calm' if last['calm'] else 'not calm'}" if last else "")
    head = [f"**Bumi** · {'⚠️ needs a look' if flags else ('✅ on track' if rebal else '⏳ waiting for its rules')}",
            f"  {what} · plans made {len(week)} of {sessions} days",
            f"  Go-live: {rebal} of {BUMI_REBALANCES} rebalances" + (f" · fills {all_slip:+.1f} bp (gate ≤ {BUMI_SLIP_BP:.0f})" if all_slip is not None else "")]
    rows = [f"{r['day']}: plan {r['plan_orders']} order{'' if r['plan_orders'] == 1 else 's'} for the next open · VIX {r['vix']:.1f}"
            + "".join(f" · {f['side']} {f['qty']} {f['sym']} at ${f['price']:,.2f}"
                      + (f" ({f['slip_bp']:+.1f} bp vs open ${f['open']:,.2f})" if f.get("slip_bp") is not None else "") for f in r.get("fills", []))
            for r in week]
    detail = ("Each day: the plan made after the close, and that morning's opening fills vs the official open "
              "(positive = paid more).\n" + "\n".join(rows) + (f"\n⚠️ " + "\n⚠️ ".join(flags) if flags else ""))
    return "\n".join(head), detail, flags


def weekly_text(first: date, last: date, swing_week, swing_all, bumi_week, bumi_all, sessions: int) -> tuple[str, list[tuple[str, str]]]:
    """(the #daily-summary post, [(bot, thread details)])."""
    sh, sd, _ = swing_section(swing_week, swing_all)
    bh, bd, _ = bumi_section(bumi_week, bumi_all, sessions)
    text = f"📈 **Weekly check · {first:%b %-d} – {last:%b %-d}**\n\n{sh}\n\n{bh}\n\n-# Paper vs the backtest model · details in the thread"
    return text, [("Swing", sd), ("Bumi", bd)]
