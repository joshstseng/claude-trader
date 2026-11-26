"""How Swing v1 and Bumi could share capital across two broker accounts, Jan 2020 to Oct 2026.

Bumi compounds on its Alpaca-style account. Swing v1 trades whole MNQ contracts sized from a fixed reference amount.
At each month end, cash is moved so the futures account returns to its target. Transfer delay, taxes and T-bill interest on futures cash are ignored.
"""
import numpy as np
import pandas as pd

from app.backtest.bumi import run as bumi_run
from app.research.swing.intraday import sharpe
from app.research.swing.x24_real import mnq, nsx

A, Z = "2020-01-02", "2026-10-30"
bm, br = bumi_run(True); bu = pd.Series(br.equity, index=pd.to_datetime(bm.dates)).pct_change().loc[A:Z].dropna(); n = nsx(); CACHE = {}


def v1(size):
    if size not in CACHE:
        p, c, _ = mnq(n, size); CACHE[size] = (p.reindex(bu.index).fillna(0.), c.reindex(bu.index).fillna(0.))
    return CACHE[size]


def sim(total, fut, size):
    B, F = total - fut, float(fut); eq = []; lo = F; moved = 0.0; top = 0
    p, c = v1(size) if fut else (pd.Series(0., index=bu.index), pd.Series(0., index=bu.index))
    for d, r, pnl in zip(bu.index, bu.to_numpy(), p.to_numpy()):
        B *= 1 + r; F += pnl; lo = min(lo, F); eq.append(B + F)
        nx = bu.index.searchsorted(d) + 1
        if fut and (nx == len(bu) or bu.index[nx].month != d.month):
            x = fut - F; B -= x; F = fut; moved += abs(x); top += x > 0
    e = pd.Series(eq, index=bu.index); rt = e.pct_change().fillna(e.iloc[0] / total - 1)
    return dict(end=e.iloc[-1], profit=e.iloc[-1] - total, cagr=(e.iloc[-1] / total) ** (252 / len(e)) - 1, sharpe=sharpe(rt), dd=(e / e.cummax() - 1).min(), worst_day=rt.min(), low_cash=lo, cts=c[c > 0].mean() if fut else 0, max_cts=c.max() if fut else 0, topups=top)


print(f"{'plan':<43}{'end $':>10}{'profit $':>10}{'%/yr':>7}{'Sharpe':>8}{'drop%':>7}{'worst day':>10}{'low fut cash':>13}{'avg/max MNQ':>13}")
P = [("$100k all Bumi", 100000, 0, 0), ("$75k Bumi + $25k futures, v1 at $50k size", 100000, 25000, 50000), ("$75k Bumi + $25k futures, v1 at $100k size", 100000, 25000, 100000), ("$50k Bumi + $50k futures, v1 at $100k size", 100000, 50000, 100000),
     ("$200k all Bumi", 200000, 0, 0), ("$175k Bumi + $25k futures, v1 at $100k", 200000, 25000, 100000), ("$150k Bumi + $50k futures, v1 at $100k", 200000, 50000, 100000), ("$150k Bumi + $50k futures, v1 at $200k", 200000, 50000, 200000), ("$100k Bumi + $100k futures, v1 at $100k", 200000, 100000, 100000)]
for lab, t, f, sz in P:
    r = sim(t, f, sz); print(f"{lab:<43}{r['end']:10,.0f}{r['profit']:10,.0f}{r['cagr']*100:7.1f}{r['sharpe']:8.2f}{r['dd']*100:7.1f}{r['worst_day']*100:10.2f}{r['low_cash']:13,.0f}{r['cts']:7.1f}/{r['max_cts']:.0f}")
for sz in (50000, 100000, 200000):
    p, c = v1(sz); m = p.groupby(p.index.to_period("M")).sum(); e = p.cumsum(); print(f"v1 at ${sz:,} size: days traded {(c > 0).mean():.0%}, worst day ${p.min():,.0f}, worst month ${m.min():,.0f}, worst drawdown ${(e - e.cummax()).min():,.0f}, max contracts {c.max():.0f}")
