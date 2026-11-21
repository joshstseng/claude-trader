"""One event-driven daily simulator for Snap-style systems (research lab, 2026-11-20).

Signals at the close, entries and rule exits at the next open. Stops, targets and partials are checked on each
day's range, the stop first when one day touches both (conservative). Stops only tighten, and a new trailing
level applies from the next day (no look-ahead). P&L is marked to market daily, on a fixed $50k account.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from app.research.daily import atr, rsi, sma
from app.research.portfolio import Market

ACCOUNT = 50_000.0
CORE = ("QQQ", "SPY", "IWM", "DIA")


@dataclass(frozen=True)
class Spec:
    name: str = "Snap"
    universe: tuple = CORE
    rsi_below: float = 10
    ibs_below: float = 0.1
    trend: str = "up"                 # up / any
    breadth: int = 1                  # at least this many of the universe signal the same day
    risk: float = 0.01
    breadth_boost: float = 1.0        # risk multiplier when 3+ signal together
    k_stop: float = 3.0
    exit_ma: int | None = 5
    max_days: int = 20
    target_r: float | None = None
    partial_r: float | None = None
    partial_frac: float = 0.5
    be_after_r: float | None = None
    trail_atr: float | None = None
    trail_after_r: float = 0.0
    no_progress_days: int | None = None   # leave at the next open if not above entry after this many days
    max_notional: float = 2.0         # × the account, all positions
    slip: float = 1e-4


@dataclass
class Pos:
    sym: str
    day_in: int
    entry: float
    dist: float
    stop: float
    qty: float
    qty0: float
    best: float
    realized: float = 0.0
    last_mark: float = 0.0
    partial_done: bool = False
    exit_next: bool = False
    why: str = ""


@dataclass
class Result:
    spec: Spec
    dates: list
    daily: list
    trades: list = field(default_factory=list)      # (sym, day_in, day_out, pnl, R, why)
    avg_notional: float = 0.0

    def window(self, y0=None, y1=None):
        return [p for d, p in zip(self.dates, self.daily) if (y0 is None or d.year >= y0) and (y1 is None or d.year <= y1)]

    def total(self, y0=None, y1=None):
        return sum(self.window(y0, y1))

    def sharpe(self, y0=None, y1=None):
        x = self.window(y0, y1)
        if not x:
            return 0.0
        m = sum(x) / len(x)
        sd = (sum((v - m) ** 2 for v in x) / len(x)) ** 0.5
        return m / sd * math.sqrt(252) if sd else 0.0

    def max_dd(self, y0=None, y1=None):
        run = peak = dd = 0.0
        for p in self.window(y0, y1):
            run += p
            peak = max(peak, run)
            dd = min(dd, run - peak)
        return dd

    def years(self):
        out: dict = {}
        for d, p in zip(self.dates, self.daily):
            out[d.year] = out.get(d.year, 0.0) + p
        return out

    @property
    def pf(self):
        w = sum(t[3] for t in self.trades if t[3] > 0)
        l_ = -sum(t[3] for t in self.trades if t[3] <= 0)
        return w / l_ if l_ else float("inf")

    @property
    def win(self):
        return sum(t[3] > 0 for t in self.trades) / max(1, len(self.trades))

    def line(self) -> str:
        y = self.years()
        pos = sum(v > 0 for v in y.values())
        dd = self.max_dd()
        return (f"{self.spec.name[:50]:50} n={len(self.trades):4} win {self.win * 100:3.0f}% PF {self.pf:4.2f} "
                f"${self.total() / 1000:+6.1f}k DD ${dd / 1000:+5.1f}k P/DD {self.total() / -dd if dd else 0:4.1f} "
                f"Sh {self.sharpe():4.2f} yrs {pos}/{len(y)} | Sh 16-20 {self.sharpe(2016, 2020):5.2f} "
                f"21-23 {self.sharpe(2021, 2023):5.2f} 24-26 {self.sharpe(2024, 2026):5.2f}")


class Data:
    def __init__(self, syms=CORE, market=None):
        self.m = market or Market(list(syms))
        self.ind = {}
        for s in syms:
            b, c = self.m.bars[s], self.m.c[s]
            self.ind[s] = {"r": rsi(c, 2), "s200": sma(c, 200), "a": atr(b), "ma": {n: sma(c, n) for n in (3, 5, 10, 20)},
                           "ibs": [(x.c - x.l) / (x.h - x.l) if x.h > x.l else 0.5 for x in b]}

    def signals(self, sp: Spec) -> dict:
        out = {}
        for s in sp.universe:
            d, c = self.ind[s], self.m.c[s]
            out[s] = [d["s200"][i] is not None and d["a"][i] is not None and d["r"][i] is not None
                      and (sp.trend == "any" or c[i] > d["s200"][i])
                      and (d["r"][i] < sp.rsi_below or d["ibs"][i] < sp.ibs_below) for i in range(len(c))]
        return out


def simulate(D: Data, sp: Spec, signals: dict | None = None) -> Result:
    sig = signals if signals is not None else D.signals(sp)
    bars, c = D.m.bars, D.m.c
    n = len(D.m.dates)
    pos: dict[str, Pos] = {}
    pending: list[tuple[str, float]] = []
    daily, trades, notional = [], [], 0.0

    def close(p: Pos, px: float, k: int, why: str):
        fill = px * (1 - sp.slip)
        p.realized += (fill - p.entry) * p.qty
        p.qty = 0.0
        trades.append((p.sym, p.day_in, k, p.realized, p.realized / (p.dist * p.qty0), why))

    for k in range(n):
        pnl = 0.0
        for s in list(pos):                                       # rule exits at the open
            p = pos[s]
            if p.exit_next:
                close(p, bars[s][k].o, k, p.why)
                pnl += p.realized - p.last_mark
                del pos[s]
        for s, atr_i in pending:                                  # entries at the open
            if s in pos:
                continue
            x = bars[s][k]
            e = x.o * (1 + sp.slip)
            dist = sp.k_stop * atr_i
            mult = sp.breadth_boost if len(pending) >= 3 else 1.0
            q = sp.risk * mult * ACCOUNT / dist
            used = sum(v.qty * bars[v.sym][k].o for v in pos.values())
            q = min(q, max(0.0, sp.max_notional * ACCOUNT - used) / e)
            if q * e < 100:
                continue
            pos[s] = Pos(s, k, e, dist, e - dist, q, q, x.o)
        pending = []
        for s in list(pos):                                       # the day's range
            p, x = pos[s], bars[s][k]
            done = False
            if x.l <= p.stop:
                close(p, min(x.o, p.stop), k, "stop")
                done = True
            else:
                if sp.partial_r and not p.partial_done:
                    t = p.entry + sp.partial_r * p.dist
                    if x.h >= t:
                        q = p.qty0 * sp.partial_frac
                        p.realized += (max(x.o, t) * (1 - sp.slip) - p.entry) * q
                        p.qty -= q
                        p.partial_done = True
                if sp.target_r:
                    t = p.entry + sp.target_r * p.dist
                    if x.h >= t:
                        close(p, max(x.o, t), k, "target")
                        done = True
            if done:
                pnl += p.realized - p.last_mark
                del pos[s]
                continue
            p.best = max(p.best, x.h)
            ind = D.ind[s]
            gain = (p.best - p.entry) / p.dist
            if sp.be_after_r is not None and gain >= sp.be_after_r:
                p.stop = max(p.stop, p.entry)
            if sp.trail_atr and gain >= sp.trail_after_r:
                p.stop = max(p.stop, p.best - sp.trail_atr * ind["a"][k])
            held = k - p.day_in + 1
            if sp.exit_ma and c[s][k] > ind["ma"][sp.exit_ma][k]:
                p.exit_next, p.why = True, "average"
            elif held >= sp.max_days:
                p.exit_next, p.why = True, "time"
            elif sp.no_progress_days and held >= sp.no_progress_days and c[s][k] <= p.entry:
                p.exit_next, p.why = True, "no progress"
            mark = p.realized + (c[s][k] - p.entry) * p.qty
            pnl += mark - p.last_mark
            p.last_mark = mark
        if k < n - 1:
            today = [s for s in sp.universe if sig[s][k]]
            if len(today) >= sp.breadth:
                pending = [(s, D.ind[s]["a"][k]) for s in today if s not in pos or pos[s].exit_next]
        daily.append(pnl)
        notional += sum(v.qty * c[v.sym][k] for v in pos.values())
    return Result(sp, D.m.dates, daily, trades, notional / n)


def shifted_signals(D: Data, sp: Spec, frac: float) -> dict:
    """The random-timing control: slide the real signal calendar along each ETF's eligible days by the same
    fraction, keeping the signal count and how signals cluster."""
    real = D.signals(sp)
    out = {}
    for s in sp.universe:
        d, cl = D.ind[s], D.m.c[s]
        e = [i for i in range(len(cl)) if d["s200"][i] is not None and d["a"][i] is not None
             and (sp.trend == "any" or cl[i] > d["s200"][i])]
        o, m = int(frac * len(e)), len(e)
        v = [False] * len(cl)
        for j, i in enumerate(e):
            if real[s][i]:
                v[e[(j + o) % m]] = True
        out[s] = v
    return out


__all__ = ["Spec", "Data", "simulate", "shifted_signals", "replace", "CORE"]
