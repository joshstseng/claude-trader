"""Portfolio-level daily simulator for the research lab (2026-11-20): compounding equity, cash, margin interest,
idle cash in T-bills (BIL) if asked. Decisions at each close set target weights (fraction of equity per symbol);
trades happen at the next open, only for symbols whose target changed. 1 bp slippage each way.

Used to compare Snap variants and trend/core ideas against simply holding QQQ or SPY.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from app.research import data
from app.research.daily import atr, rsi, sma

SLIP = 0.0001


@dataclass
class Result:
    name: str
    equity: list[float]
    dates: list[date]
    trades: int = 0
    exposure: float = 0.0            # average gross exposure as a fraction of equity
    notes: dict = field(default_factory=dict)

    def cagr(self, y0: int | None = None, y1: int | None = None) -> float:
        idx = [i for i, d in enumerate(self.dates) if (y0 is None or d.year >= y0) and (y1 is None or d.year <= y1)]
        if len(idx) < 2:
            return 0.0
        a, b = idx[0], idx[-1]
        start = self.equity[a - 1] if a > 0 else self.equity[a]
        yrs = (self.dates[b] - (self.dates[a - 1] if a > 0 else self.dates[a])).days / 365.25
        return (self.equity[b] / start) ** (1 / yrs) - 1 if yrs > 0 and start > 0 else 0.0

    def max_dd(self) -> float:
        peak, dd = self.equity[0], 0.0
        for v in self.equity:
            peak = max(peak, v)
            dd = min(dd, v / peak - 1)
        return dd

    def sharpe(self) -> float:
        r = [b / a - 1 for a, b in zip(self.equity, self.equity[1:])]
        m = sum(r) / len(r)
        sd = (sum((x - m) ** 2 for x in r) / len(r)) ** 0.5
        return m / sd * math.sqrt(252) if sd else 0.0

    def line(self) -> str:
        return (f"{self.name[:46]:46} ${self.equity[-1] / 1000:7,.0f}k  CAGR {self.cagr() * 100:5.1f}%  "
                f"maxDD {self.max_dd() * 100:5.0f}%  Sharpe {self.sharpe():4.2f} | 16-20 {self.cagr(2016, 2020) * 100:5.1f}% "
                f"21-23 {self.cagr(2021, 2023) * 100:5.1f}% 24-26 {self.cagr(2024, 2026) * 100:5.1f}% | "
                f"trades {self.trades} expo {self.exposure:.2f}")


class Market:
    """Aligned daily bars for a set of symbols (dates where all exist)."""

    def __init__(self, syms: list[str], end: date = date(2026, 10, 30)):
        raw = {s: {b.t.date(): b for b in data.daily(s, fetch=False)} for s in syms}
        common = sorted(set.intersection(*(set(v) for v in raw.values())))
        self.dates = [d for d in common if d <= end]
        self.bars = {s: [raw[s][d] for d in self.dates] for s in syms}
        self.c = {s: [b.c for b in self.bars[s]] for s in syms}


def run(name: str, mkt: Market, decide, *, start_equity: float = 50_000.0, margin_rate: float = 0.07,
        idle: str | None = None, max_gross: float = 2.0) -> Result:
    """decide(k, held_weights) -> {sym: weight} at the close of day k (weights of equity; idle cash added if set)."""
    n = len(mkt.dates)
    cash, shares = start_equity, {}
    target: dict[str, float] = {}
    eq, trades, gross_sum = [], 0, 0.0
    pending = None
    for k in range(n):
        if k > 0 and pending is not None:                              # trade at today's open
            want = dict(pending)
            if idle:
                want[idle] = max(0.0, 1.0 - sum(w for s, w in want.items() if s != idle))
            tot = sum(want.values())
            if tot > max_gross:
                want = {s: w * max_gross / tot for s, w in want.items()}
            equity_open = cash + sum(q * mkt.bars[s][k].o for s, q in shares.items())
            for s in set(want) | set(shares):
                w_new, w_old = want.get(s, 0.0), target.get(s, 0.0)
                if abs(w_new - w_old) < 1e-9 and s in shares:
                    continue
                px = mkt.bars[s][k].o
                q_new = w_new * equity_open / px
                dq = q_new - shares.get(s, 0.0)
                if abs(dq) * px < 1.0:
                    continue
                cash -= dq * px + abs(dq) * px * SLIP
                trades += 1
                if q_new > 1e-9:
                    shares[s] = q_new
                else:
                    shares.pop(s, None)
            target = want
        if cash < 0:
            cash *= 1 + margin_rate / 252
        value = cash + sum(q * mkt.c[s][k] for s, q in shares.items())
        eq.append(value)
        gross_sum += sum(q * mkt.c[s][k] for s, q in shares.items() if s != idle) / value if value > 0 else 0
        pending = decide(k, target)
    return Result(name, eq, mkt.dates, trades, gross_sum / n)


# ------------------------------------------------------------------ building blocks

class SnapSignals:
    """Snap's rules on one underlying (next-open version). want[k]: at the close of day k, Snap wants to hold this
    after the next open (True on a signal day and while in a trade; False on the exit or stop day)."""

    def __init__(self, mkt: Market, und: str, rsi_below=10, ibs_below=0.1, trend=200, exit_ma=5, atr_mult=3.0,
                 max_days=20, use_stop=True):
        b, c = mkt.bars[und], mkt.c[und]
        r, tr, ex, a = rsi(c, 2), sma(c, trend), sma(c, exit_ma), atr(b)
        self.want = [False] * len(b)
        i = 0
        while i < len(b) - 1:
            ibs = (c[i] - b[i].l) / (b[i].h - b[i].l) if b[i].h > b[i].l else 0.5
            if tr[i] is None or a[i] is None or c[i] <= tr[i] or not (r[i] < rsi_below or ibs < ibs_below):
                i += 1
                continue
            self.want[i] = True                                       # buy at the next open
            k = i + 1
            stop = b[k].o - atr_mult * a[i]
            j = k
            while j < len(b) - 1:
                if (use_stop and b[j].l <= stop) or c[j] > ex[j] or j - i >= max_days:
                    break                                              # sell at the next open
                self.want[j] = True
                j += 1
            i = j if j > i else i + 1


def trend_flag(mkt: Market, sym: str, n: int = 200) -> list[bool]:
    c, m = mkt.c[sym], sma(mkt.c[sym], n)
    return [m[k] is not None and c[k] > m[k] for k in range(len(c))]
