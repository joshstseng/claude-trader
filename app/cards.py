"""What a trade's cards say (Step 1b.9). Plain functions over the trade log rows, so they're easy to test.

    waiting_card   in #live-trades right after Approve, until the entry fills
    live_card      in #live-trades while in the trade (refreshed about every minute)
    closed_card    in #closed-trades when it ends (with an @mention)
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ICON = {"target": "✅", "stop": "❌", "flat": "➖", "flatten": "🛑", "manual": ""}   # closed by you: no emoji
WORD = {"target": "target hit", "stop": "stopped out", "flat": "sold at the close", "flatten": "closed by /flatten",
        "manual": "closed by you"}
EVENT = {"stop_moved": "stop", "breakeven": "stop → break-even", "target_moved": "target",
         "closed_manually": "closed by you", "cancelled": "cancelled"}


def _m(x) -> str:
    return "?" if x is None else f"${float(x):,.2f}"


def _signed(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def _r(x: float) -> str:
    return f"{x:+.2f}R".replace("-", "−")


def _et(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(NY).strftime("%-I:%M %p")
    except ValueError:
        return "?"


def _pct(a: float, b: float) -> str:
    return f"{(a / b - 1) * 100:+.1f}%".replace("-", "−")


def changes(events) -> str | None:
    parts = []
    for e in events:
        if e["kind"] in ("stop_moved", "breakeven", "target_moved"):
            parts.append(f"{EVENT[e['kind']]} {_m(e['old_value'])} → {_m(e['new_value'])} ({_et(e['at'])})")
    return "; ".join(parts) if parts else None


def waiting_card(order, now: datetime, timeout_s: int = 120) -> tuple[str, str]:
    """(title, body) while the limit entry waits to fill."""
    sent = datetime.fromisoformat(order["submitted_at"])
    left = max(0, int(timeout_s - (now - sent).total_seconds()))
    title = f"⏳ {order['symbol']} · waiting for fill"
    body = (f"Limit **{_m(order['limit_price'])}** · {order['qty']} sh · stop {_m(order['stop'])} · "
            f"target {_m(order['target'])}\n"
            + (f"Cancels in {left // 60}:{left % 60:02d} if not filled" if left else "Checking the fill…"))
    return title, body


def live_card(order, signal, price: float | None, now: datetime, flat_by: dtime, events=()) -> tuple[str, str, float | None]:
    """(title, body, unrealized $) while in the trade. The live P&L is the title, so it reads at a glance."""
    fill, qty = order["filled_price"], order["filled_qty"] or order["qty"]
    risk = (signal["entry"] - signal["stop"]) if signal else None
    pnl = (price - fill) * qty if price is not None and fill is not None else None
    if pnl is not None:
        r = f" · {_r((price - fill) / risk)}" if risk else ""
        title = f"{'🟢' if pnl >= 0 else '🔴'} {order['symbol']} · {_signed(pnl)}{r}"
    else:
        title = f"⚪ {order['symbol']} · P&L unavailable"
    lines = [f"{qty} sh · in **{_m(fill)}** at {_et(order['filled_at'])} ET · now **{_m(price)}**"]
    block = [f"Stop    {_m(order['stop']):<10}" + (f" ({_pct(order['stop'], price)} away)" if price else ""),
             f"Target  {_m(order['target']):<10}" + (f" ({_pct(order['target'], price)} away)" if price else "")]
    lines.append("```\n" + "\n".join(block) + "\n```")
    flat_at = datetime.combine(now.astimezone(NY).date(), flat_by, tzinfo=NY)
    left = flat_at - now.astimezone(NY)
    if left > timedelta(0):
        h, m = divmod(int(left.total_seconds()) // 60, 60)
        lines.append(f"Sells at {flat_at:%-I:%M %p} ET ({f'{h}h ' if h else ''}{m}m)")
    else:
        lines.append(f"Selling now ({flat_at:%-I:%M %p} ET)")
    c = changes(events)
    if c:
        lines.append(f"Changes: {c}")
    lines.append(f"-# updated {now.astimezone(NY):%-I:%M %p} ET")
    return title, "\n".join(lines), pnl


def closed_card(order, signal, events=(), backtest=None) -> tuple[str, str]:
    """(headline, body) for #closed-trades. backtest = the 4:15 outcome row (result, r_gross) or None."""
    reason = order["exit_reason"] or "?"
    fill, out_px, qty = order["filled_price"], order["exit_price"], order["filled_qty"] or order["qty"]
    pnl = order["pnl_usd"] or 0.0
    risk = (signal["entry"] - signal["stop"]) if signal else None
    r = f" · {_r((out_px - fill) / risk)}" if risk and fill is not None and out_px is not None else ""
    icon = ICON.get(reason, "•")
    head = f"{icon + ' ' if icon else ''}{order['symbol']} · {WORD.get(reason, reason)} · **{_signed(pnl)}**{r}"
    held = ""
    try:
        a = datetime.fromisoformat(str(order["filled_at"]).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(order["exited_at"]).replace("Z", "+00:00"))
        mins = int((b - a).total_seconds() // 60)
        held = f" · held {mins // 60}h {mins % 60}m" if mins >= 60 else f" · held {mins}m"
    except (TypeError, ValueError):
        pass
    lines = [f"In {_m(fill)} ({_et(order['filled_at'])}) → out {_m(out_px)} ({_et(order['exited_at'])}) · "
             f"{qty} sh{held}"]
    c = changes(events)
    if c:
        lines.append(f"Changes: {c}")
    if backtest is not None and backtest["r_gross"] is not None:
        lines.append(f"Backtest said: {ICON.get(backtest['result'], '?')} {_r(backtest['r_gross'])}")
    return head, "\n".join(lines)
