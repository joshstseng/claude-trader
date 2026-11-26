"""The trade journal (/journal in Uri): every bot's paper trades and fills as two CSV files.

The contract for any bot, now or later: after each market day, save a daily record under fleet key
daily:<bot>:<YYYY-MM-DD> (JSON) with
    trades   closed trades that day: side ("long"/"short" or 1/-1), qty, entry, exit, pnl, and either
             time_in/time_out (intraday) or day_in/day_out (multi-day), plus why (exit reason)
    fills    fills that day: side, qty, price, and optionally time, sym, model price (model_px or open), slip_bp, why
    symbol   the bot's symbol, when trades/fills don't name one
Uri reads them all; nothing else needs to change for a new bot to appear here or in the weekly check.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date

TRADE_COLS = ["bot", "symbol", "side", "entry_date", "entry_time", "entry_price", "exit_date", "exit_time", "exit_price",
              "shares", "pnl_usd", "pnl_pct", "held", "exit_reason", "model_day_pnl_usd"]
FILL_COLS = ["bot", "date", "time", "symbol", "side", "shares", "price", "model_price", "slippage_bp", "note"]


def records(pairs: list[tuple[str, str]], bot: str | None = None, start: str | None = None) -> list[tuple[str, dict]]:
    """(bot, record) for keys daily:<bot>:<day>, oldest first, optionally one bot and from a date."""
    out = []
    for key, value in pairs:
        parts = key.split(":")
        if len(parts) != 3:
            continue
        who, day = parts[1], parts[2]
        if (bot and who != bot) or (start and day < start):
            continue
        try:
            out.append((who, json.loads(value)))
        except ValueError:
            continue
    return sorted(out, key=lambda x: (x[1].get("day", ""), x[0]))


def _side(x) -> str:
    return "long" if x in (1, "long", "buy") else "short" if x in (-1, "short", "sell") else str(x)


def _held(t: dict) -> str:
    if t.get("time_in") and t.get("time_out"):
        a = int(t["time_in"][:2]) * 60 + int(t["time_in"][3:5])
        b = int(t["time_out"][:2]) * 60 + int(t["time_out"][3:5])
        m = max(0, b - a)
        return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"
    if t.get("day_in") and t.get("day_out"):
        d = (date.fromisoformat(t["day_out"]) - date.fromisoformat(t["day_in"])).days
        return f"{d} day{'' if d == 1 else 's'}"
    return ""


def trade_rows(recs: list[tuple[str, dict]]) -> list[dict]:
    rows = []
    for who, r in recs:
        for t in r.get("trades") or []:
            side = _side(t.get("side", "long"))
            entry, exit_ = t.get("entry"), t.get("exit")
            pct = ((exit_ / entry - 1) * (1 if side == "long" else -1) * 100) if entry and exit_ else None
            rows.append({"bot": who, "symbol": t.get("sym") or r.get("symbol", ""), "side": side,
                         "entry_date": t.get("day_in") or r["day"], "entry_time": t.get("time_in", ""),
                         "entry_price": round(entry, 4) if entry else "", "exit_date": t.get("day_out") or r["day"],
                         "exit_time": t.get("time_out", ""), "exit_price": round(exit_, 4) if exit_ else "",
                         "shares": t.get("qty", ""), "pnl_usd": t.get("pnl", ""), "pnl_pct": round(pct, 3) if pct is not None else "",
                         "held": _held(t), "exit_reason": t.get("why", ""),
                         "model_day_pnl_usd": r.get("model_pnl", "") if "model_pnl" in r else ""})
    return rows


def fill_rows(recs: list[tuple[str, dict]]) -> list[dict]:
    rows = []
    for who, r in recs:
        for f in r.get("fills") or []:
            model = f.get("model_px", f.get("open"))
            rows.append({"bot": who, "date": f.get("day") or r["day"], "time": f.get("time", ""),
                         "symbol": f.get("sym") or r.get("symbol", ""), "side": f.get("side", ""), "shares": f.get("qty", ""),
                         "price": f.get("price", ""), "model_price": round(model, 4) if model else "",
                         "slippage_bp": f.get("slip_bp") if f.get("slip_bp") is not None else "", "note": f.get("why") or ""})
    return rows


def to_csv(rows: list[dict], cols: list[str]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


RECENT = 5
BLURB = {"swing": "QQQ · intraday breakout · paper", "bumi": "index dips + calm-market QQQ · paper"}


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def bot_section(who: str, recs: list[dict]) -> str:
    """A short, readable block for one bot."""
    name = who.capitalize()
    head = f"**{name}**" + (f"\n-# {BLURB[who]}" if who in BLURB else "")
    if not recs:
        return head + "\nNo daily records yet. They start after this bot's next market day."
    first = recs[0]["day"]
    trades = trade_rows([(who, r) for r in recs])
    fills = fill_rows([(who, r) for r in recs])
    since = f"since {date.fromisoformat(first):%b %-d}"
    if not trades:
        return head + f"\nNo closed trades yet ({since}, {len(recs)} market day{'' if len(recs) == 1 else 's'})."
    pnl = [float(t["pnl_usd"]) for t in trades]
    wins = sum(x > 0 for x in pnl)
    lines = [head, f"{len(trades)} closed trade{'' if len(trades) == 1 else 's'} · {wins} won · **{_usd(sum(pnl))}** · {since}",
             f"Win rate {wins / len(trades):.0%} · avg {_usd(sum(pnl) / len(pnl))} · best {_usd(max(pnl))} · worst {_usd(min(pnl))}"]
    model = sum(r.get("model_pnl") or 0 for r in recs) if any("model_pnl" in r for r in recs) else None
    slips = [float(f["slippage_bp"]) for f in fills if f["slippage_bp"] != ""]
    extra = []
    if model is not None:
        extra.append(f"model {_usd(model)}")
    if slips:
        avg = sum(slips) / len(slips)
        extra.append(f"fills {abs(avg):.1f} bp {'worse' if avg > 0 else 'better'} than the model")
    if extra:
        lines.append(" · ".join(extra).capitalize())
    recent = trades[-RECENT:][::-1]
    lines.append("Recent trades:")
    for t in recent:
        icon = "✅" if float(t["pnl_usd"]) > 0 else "❌" if float(t["pnl_usd"]) < 0 else "➖"
        lines.append(f"{icon} `{date.fromisoformat(t['exit_date']):%b %-d}` {t['side']} {t['symbol']} · **{_usd(float(t['pnl_usd']))}**"
                     + (f" · {t['held']}" if t["held"] else "") + (f" · {t['exit_reason']}" if t["exit_reason"] else ""))
    if len(trades) > RECENT:
        more = len(trades) - RECENT
        lines.append(f"-# + {more} older trade{'' if more == 1 else 's'} in the spreadsheet")
    return "\n".join(lines)


def build(pairs: list[tuple[str, str]], bot: str | None = None, start: str | None = None,
          bots: tuple[str, ...] = ("swing", "bumi")) -> tuple[bytes, str]:
    """(a zip with <bot>-trades.csv and <bot>-fills.csv per bot, the message). bots: always listed, even with no records."""
    import zipfile
    recs = records(pairs, None, start)
    have = sorted({w for w, _ in recs})
    if bot:
        show = [bot]
    else:
        show = list(dict.fromkeys([*bots, *have]))
    by = {w: [r for who, r in recs if who == w] for w in show}
    span = f" · from {date.fromisoformat(start):%b %-d}" if start else ""
    if bot and bot not in have and bot not in bots:
        known = ", ".join(w.capitalize() for w in dict.fromkeys([*bots, *have]))
        return b"", f"📒 **Trade journal**{span}\nNo bot called **{bot}** has records. Try: {known}."
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for w in show:
            pairs_w = [(w, r) for r in by[w]]
            z.writestr(f"{w}-trades.csv", to_csv(trade_rows(pairs_w), TRADE_COLS))
            z.writestr(f"{w}-fills.csv", to_csv(fill_rows(pairs_w), FILL_COLS))
    text = f"📒 **Trade journal**{span}\n\n" + "\n\n".join(bot_section(w, by[w]) for w in show)
    return buf.getvalue(), text
