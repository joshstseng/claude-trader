"""After the close: what every signal of the day did, and the summary for #daily-summary.

For each signal (alerted or held back) without a result yet: the day's 5-minute bars from Alpaca
-> app.outcomes.resolve -> saved in the trade log. Then one short summary: the alerted signals,
all signals, and your picks (the ones you tapped Took it on).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable

from app import outcomes, tradelog
from app.market import Session
from app.outcomes import Bar

log = logging.getLogger(__name__)
ICON = {"target": "✅", "stop": "❌", "flat": "➖", "no_data": "❔"}
BarsFetcher = Callable[[list[str], date], dict[str, list[Bar]]]


def flat_by_for(session: Session | None, rules: dict) -> dtime:
    """3:55 PM normally; 5 minutes before an early close (12:55 PM)."""
    t = dtime.fromisoformat(rules.get("flat_by", "15:55"))
    if session and session.early_close:
        early = (datetime.combine(session.day, session.close) - timedelta(minutes=5)).time()
        t = min(t, early)
    return t


def resolve_day(trade_log: tradelog.TradeLog, day: str, *, fetch: BarsFetcher, flat_by: dtime,
                cost_pct: float, strategy: str = "orb", source: str = "live",
                run_id: int | None = None) -> int:
    """Work out every unresolved signal of the day. Returns how many were resolved."""
    rows = [r for r in trade_log.signals(strategy=strategy, source=source, date=day, run_id=run_id)
            if r["entry"] is not None and trade_log.outcome(r["id"]) is None]
    if not rows:
        return 0
    bars = fetch(sorted({r["symbol"] for r in rows}), date.fromisoformat(day))
    for r in rows:
        o = outcomes.resolve(entry=r["entry"], stop=r["stop"], target=r["target"],
                             entry_at=outcomes.entry_datetime(day, r["trigger_time"]),
                             bars=bars.get(r["symbol"], []), flat_by=flat_by, qty=r["qty"],
                             cost_pct=cost_pct)
        trade_log.save_outcome(r["id"], o)
    log.info("[ORB] %s: worked out %d signal results", day, len(rows))
    return len(rows)


def _group(items: list[dict]) -> tuple[str, float, float]:
    counts = {k: sum(1 for i in items if i["result"] == k) for k in ICON}
    parts = [f"{counts[k]} {ICON[k]}" for k in ("target", "stop", "flat", "no_data") if counts[k]]
    r = sum(i["r"] or 0 for i in items)
    usd = sum(i["usd"] or 0 for i in items)
    return " · ".join(parts), r, usd


def _fmt(r: float, usd: float, n: int) -> str:
    avg = f" (avg {r / n:+.2f}R)" if n > 1 else ""
    return f"**{r:+.2f}R**{avg} · {'+' if usd >= 0 else '−'}${abs(usd):,.2f}"


def summary_text(trade_log: tradelog.TradeLog, day: str, *, strategy: str = "orb", source: str = "live",
                 run_id: int | None = None, cost_pct: float = 0.0003, scanned: bool = True) -> str:
    """The #daily-summary message (under Discord's 2,000 characters).
    `scanned=False`: the bot never checked today (e.g. it started after the scan window)."""
    label = datetime.strptime(day, "%Y-%m-%d").strftime("%a %b %-d")
    tag = "REPLAY · " if source != "live" else ""
    rows = trade_log.signals(strategy=strategy, source=source, date=day, run_id=run_id)
    if not rows:
        if not scanned:
            return f"{tag}**[ORB] {label}** · no checks ran today (the bot started after the scan window)."
        return f"{tag}**[ORB] {label}** · no signals today: no stock on the focus list broke out with enough volume."

    items = []
    for r in rows:
        o, a, resp = trade_log.outcome(r["id"]), trade_log.alert(r["id"]), trade_log.latest_response(r["id"])
        items.append({"sym": r["symbol"], "time": r["trigger_time"],
                      "result": o["result"] if o else "no_data",
                      "r": o["r_multiple"] if o else None, "usd": o["pnl_usd"] if o else None,
                      "alerted": bool(a and a["sent"]), "held": a["held_reason"] if a and not a["sent"] else None,
                      "you": resp["action"] if resp else None})
    alerted = [i for i in items if i["alerted"]]
    picks = [i for i in items if i["you"] == "took"]
    held = [i for i in items if not i["alerted"]]

    lines = [f"{tag}**[ORB] {label}** · {len(items)} signals · {len(alerted)} alerted · you took {len(picks)}"]
    if alerted:
        c, r, usd = _group(alerted)
        lines.append(f"**Alerted ({len(alerted)}):** {c} → {_fmt(r, usd, len(alerted))}")
    c, r, usd = _group(items)
    lines.append(f"**All signals ({len(items)}):** {c} → {_fmt(r, usd, len(items))}")
    if picks:
        c, r, usd = _group(picks)
        lines.append(f"**Your picks ({len(picks)}):** {c} → {_fmt(r, usd, len(picks))}")
    if alerted:
        lines.append("")
        for i in alerted:
            you = f" · you: {'took it' if i['you'] == 'took' else 'skipped'}" if i["you"] else ""
            res = f"{i['result']} {i['r']:+.2f}R" if i["r"] is not None else "no data"
            lines.append(f"`{i['time']}` **{i['sym']}** {ICON[i['result']]} {res}{you}")
    if held:
        shown = ", ".join(f"{i['sym']} {ICON[i['result']]}" + (f" {i['r']:+.1f}R" if i["r"] is not None else "")
                          for i in held[:12])
        more = f" +{len(held) - 12} more" if len(held) > 12 else ""
        lines.append(f"\n_Held back ({len(held)}):_ {shown}{more}")
    lines.append(f"\n-# R after {cost_pct * 100:.2f}% costs per side · flat at 3:55 PM if neither hit · "
                 f"alerts only, no orders were placed")
    text = "\n".join(lines)
    return text if len(text) <= 1990 else text[:1980] + "…"
