"""Snap (strategy id snap): buys short, sharp dips in the big index ETFs while they're in an uptrend, and sells
the snap-back. Daily bars; signals at the close, filled at the close (a market-on-close order a minute before
the bell). Found by the research lab on 2026-11-20 (plans/snap-strategy.md); backtest only for now.

    universe   QQQ, SPY, IWM, DIA
    entry      at the close, when the close is above its 200-day average AND
               (the 2-day RSI is under 10 OR the close sits in the bottom 10% of the day's range: IBS < 0.1)
    exit       at the first close above the 5-day average, or after 20 trading days
    stop       3 × ATR(14) below the entry, checked on each day's low (a gap below it fills at the open)
    size       so the stop loses 1% of the account; at most 2× the account in one position
    one position per ETF at a time; re-entry allowed the day after an exit
    fills.mode "next_open" (the live plan, plans/snap-paper.md): decide after the close on final bars, buy and
    sell at the next open (market-on-open orders); the stop rests as a GTC order from the entry day on
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.research.daily import atr, rsi, sma


@dataclass
class SnapTrade:
    sym: str
    day_in: str
    day_out: str
    entry: float
    exit: float
    stop: float
    shares: float
    why_in: str
    why_out: str
    pnl_usd: float = 0.0
    r: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def ibs(b) -> float:
    return (b.c - b.l) / (b.h - b.l) if b.h > b.l else 0.5


def signal(bars: list, i: int, s: dict, cache: dict | None = None) -> str | None:
    """Why to buy at the close of bars[i], or None."""
    c = [b.c for b in bars] if cache is None else cache["c"]
    e = s["entry"]
    trend = sma(c, e["trend_sma"]) if cache is None else cache["trend"]
    r = rsi(c, e["rsi_period"]) if cache is None else cache["rsi"]
    if trend[i] is None or r[i] is None or c[i] <= trend[i]:
        return None
    if r[i] < e["rsi_below"]:
        return f"RSI(2) {r[i]:.1f}"
    if ibs(bars[i]) < e["ibs_below"]:
        return f"IBS {ibs(bars[i]):.2f}"
    return None


def run_symbol(sym: str, bars: list, s: dict) -> list[SnapTrade]:
    c = [b.c for b in bars]
    cache = {"c": c, "trend": sma(c, s["entry"]["trend_sma"]), "rsi": rsi(c, s["entry"]["rsi_period"])}
    ex, st, acct = s["exit"], s["stop"], s["account"]
    exit_ma = sma(c, ex["above_sma"])
    a = atr(bars, st["atr_period"])
    slip = s["costs"]["slippage_bp"] / 1e4
    risk_usd = acct["size_usd"] * acct["risk_pct"]
    out: list[SnapTrade] = []
    nxt = (s.get("fills") or {}).get("mode") == "next_open"
    i = 0
    while i < len(bars) - 1:
        why = signal(bars, i, s, cache)
        if a[i] is None or why is None or (nxt and i + 2 >= len(bars)):
            i += 1
            continue
        if nxt:
            k = i + 1                                    # bought at the next open
            entry = bars[k].o * (1 + slip)
            dist = st["atr_mult"] * a[i]
            stop = entry - dist
            shares = min(risk_usd / dist, acct["max_leverage"] * acct["size_usd"] / entry)
            j = k
            while True:
                x = bars[j]
                if x.l <= stop:
                    px, why_out = min(x.o, stop), "stop"
                    break
                done = exit_ma[j] is not None and c[j] > exit_ma[j]
                if (done or j - i >= ex["max_days"]) and j + 1 < len(bars):
                    j += 1                               # decided at this close, sold at the next open
                    px = bars[j].o
                    why_out = f"close above the {ex['above_sma']}-day average" if done else "time"
                    break
                if j == len(bars) - 1:
                    px, why_out = c[j], "end of data"
                    break
                j += 1
            px *= (1 - slip)
            pnl = (px - entry) * shares
            out.append(SnapTrade(sym, bars[k].t.date().isoformat(), bars[j].t.date().isoformat(), round(entry, 4),
                                 round(px, 4), round(stop, 4), round(shares, 4), why, why_out, round(pnl, 2),
                                 round(pnl / risk_usd, 3)))
            i = j                                        # can buy again at this day's close signal
            continue
        entry = c[i] * (1 + slip)
        dist = st["atr_mult"] * a[i]
        stop = entry - dist
        shares = min(risk_usd / dist, acct["max_leverage"] * acct["size_usd"] / entry)
        j = i + 1
        while True:
            x = bars[j]
            if x.l <= stop:
                px, why_out = min(x.o, stop), "stop"
                break
            if exit_ma[j] is not None and c[j] > exit_ma[j]:
                px, why_out = c[j], f"close above the {ex['above_sma']}-day average"
                break
            if j - i >= ex["max_days"] or j == len(bars) - 1:
                px, why_out = c[j], "time" if j - i >= ex["max_days"] else "end of data"
                break
            j += 1
        px *= (1 - slip)
        pnl = (px - entry) * shares
        out.append(SnapTrade(sym, bars[i].t.date().isoformat(), bars[j].t.date().isoformat(), round(entry, 4),
                             round(px, 4), round(stop, 4), round(shares, 4), why, why_out, round(pnl, 2),
                             round(pnl / risk_usd, 3)))
        i = j + 1
    return out
