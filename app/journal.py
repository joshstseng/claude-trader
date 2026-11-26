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


def build(pairs: list[tuple[str, str]], bot: str | None = None, start: str | None = None) -> tuple[bytes, bytes, str]:
    """(trades.csv, fills.csv, a one-line summary)."""
    recs = records(pairs, bot, start)
    trades, fills = trade_rows(recs), fill_rows(recs)
    pnl = sum(float(t["pnl_usd"]) for t in trades if t["pnl_usd"] != "")
    bots = sorted({w for w, _ in recs})
    first = recs[0][1]["day"] if recs else None
    summary = (f"📒 **Trade journal** · {', '.join(b.capitalize() for b in bots) or 'no bots yet'}"
               + (f" · since {first}" if first else "") + f" · {len(trades)} closed trade{'' if len(trades) == 1 else 's'} · "
               f"{len(fills)} fill{'' if len(fills) == 1 else 's'} · paper P&L {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f}")
    return to_csv(trades, TRADE_COLS), to_csv(fills, FILL_COLS), summary
