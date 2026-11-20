"""Daily-bar strategies on ETFs for the research lab. Signals are read at the close and filled at the close
(a market-on-close order sent a minute before the bell); 1 bp of slippage each way, no commission (Alpaca).
Every trade has a protective stop k × ATR(14) away, sized so the stop loses 1% of the account (notional capped
at 2× the account, Alpaca's overnight margin)."""

from __future__ import annotations

from app.research.data import D
from app.research.evaluate import ACCOUNT, RISK, Trade

SLIP = 0.0001


def sma(x: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def rsi(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    g = l_ = 0.0
    for i in range(1, len(x)):
        d = x[i] - x[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            g += up / n
            l_ += dn / n
            if i == n:
                out[i] = 100 - 100 / (1 + g / l_) if l_ else 100.0
        else:
            g = (g * (n - 1) + up) / n
            l_ = (l_ * (n - 1) + dn) / n
            out[i] = 100 - 100 / (1 + g / l_) if l_ else 100.0
    return out


def atr(b: list[D], n: int = 14) -> list[float | None]:
    tr = [b[0].h - b[0].l] + [max(x.h - x.l, abs(x.h - p.c), abs(x.l - p.c)) for p, x in zip(b, b[1:])]
    out: list[float | None] = [None] * len(b)
    a = None
    for i, v in enumerate(tr):
        if i < n - 1:
            continue
        a = sum(tr[:n]) / n if i == n - 1 else (a * (n - 1) + v) / n
        out[i] = a
    return out


def simulate(sym: str, b: list[D], entry, exit_, *, side: int = 1, k_stop: float = 3.0, max_days: int = 20,
             note: str = "") -> list[Trade]:
    """entry(i) -> bool at the close of day i; exit_(i, j) -> bool at the close of day j (entered on day i)."""
    a = atr(b)
    out: list[Trade] = []
    i = 0
    while i < len(b) - 1:
        if a[i] is None or not entry(i):
            i += 1
            continue
        p_in = b[i].c * (1 + SLIP * side)
        stop = p_in - side * k_stop * a[i]
        qty = min(RISK * ACCOUNT / (k_stop * a[i]), 2 * ACCOUNT / p_in)
        j, p_out = i + 1, None
        while j < len(b):
            x = b[j]
            if (x.l <= stop) if side > 0 else (x.h >= stop):
                p_out = min(x.o, stop) if side > 0 else max(x.o, stop)
                break
            if exit_(i, j) or j - i >= max_days or j == len(b) - 1:
                p_out = x.c
                break
            j += 1
        p_out *= (1 - SLIP * side)
        out.append(Trade(sym, side, b[i].t, b[j].t, p_in, p_out, qty, 0.0, note))
        i = j + 1 if j > i else i + 1          # can re-enter the day after the exit
    return out
