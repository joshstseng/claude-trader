"""Step 4: robustness of the two screen survivors, using pre-2019 data only. Base settings stay as screened."""
import itertools

import numpy as np
import pandas as pd

from app.research.swing.lab import GROUPS, carry, load, simulate, stats
from app.research.swing.x2_validate import MICRO

d = load(); ALL = list(d.adj.columns)


def rank_ls(x, cols, frac=1 / 3):
    r = x[cols].rank(axis=1, pct=True); n = x[cols].notna().sum(axis=1)
    o = (r > 1 - frac).astype(float) - (r <= frac).astype(float)
    return o.where(x[cols].notna()).where(n >= 6, 0.0)


def xs(cols=ALL, frac=1 / 3, lb=252, span=90, wc=.5):
    c = carry(d, span); m = (d.adj.shift(21) - d.adj.shift(lb)) / (d.vol * 256)
    return rank_ls(wc * c.rank(axis=1, pct=True) + (1 - wc) * m.rank(axis=1, pct=True), cols, frac)


def rsi(x, n=2):
    c = x.diff(); u = c.clip(lower=0).ewm(alpha=1 / n).mean(); v = (-c.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 * u / (u + v).replace(0, np.nan)


def dip(cols, n=2, lvl=10, hold=3, ma=200):
    a = d.adj[cols]; mm = a.rolling(ma, min_periods=ma).mean(); up = (a > mm).astype(float).where(mm.notna())
    return ((rsi(a, n) < lvl).astype(float) * up).replace(0, np.nan).ffill(limit=hold).fillna(0).where(up.notna())


def sh(f, cols, **k):
    r = simulate(d, f.reindex(columns=cols), cols=cols, idm=1.5, **k).loc[:"2018-12-31"]
    return stats(r.loc["1985":"2012"].net)["sharpe"], stats(r.loc["2013":"2018"].net)["sharpe"], r


def show(k, x):
    print(f"  {k:<38} dev {x[0]:5.2f}  val {x[1]:5.2f}")


print("A. Cross-sectional carry + momentum")
show("base", sh(xs(), ALL)); show("2x costs", sh(xs(), ALL, cost_mult=2)); show("micro basket", sh(xs(MICRO), MICRO))
G = []
for fr, lb, sp, wc in itertools.product((.25, 1 / 3, .5), (126, 189, 252), (30, 90, 180), (.3, .5, .7)):
    a, b, _ = sh(xs(ALL, fr, lb, sp, wc), ALL); G.append((a, b))
G = np.array(G); print(f"  neighbors {len(G)}: val>0 {np.mean(G[:,1]>0):.0%}, val>=.3 {np.mean(G[:,1]>=.3):.0%}, val>=.5 {np.mean(G[:,1]>=.5):.0%}, median dev {np.median(G[:,0]):.2f}, median val {np.median(G[:,1]):.2f}")
for g, xsn in GROUPS.items():
    cols = [s for s in ALL if s not in xsn]; show(f"without {g}", sh(xs(cols), cols))
for g, xsn in GROUPS.items():
    if len(xsn) >= 6: show(f"only {g}", sh(xs(xsn), xsn))

print("\nB. RSI2 dip in uptrend, equity indexes")
E = GROUPS["equity"]
show("base", sh(dip(E), E)); show("2x costs", sh(dip(E), E, cost_mult=2))
for s in ("SP500", "NASDAQ", "DOW", "RUSSELL", "SP400"):
    r = simulate(d, dip([s]), cols=[s], idm=1.0).loc[:"2018-12-31"]; show("only " + s, (stats(r.loc["1985":"2012"].net)["sharpe"], stats(r.loc["2013":"2018"].net)["sharpe"]))
G = []
for n, l, h, ma in itertools.product((2, 3, 4), (5, 10, 15, 25), (1, 3, 5), (100, 200)):
    a, b, _ = sh(dip(E, n, l, h, ma), E); G.append((a, b))
G = np.array(G); print(f"  neighbors {len(G)}: val>0 {np.mean(G[:,1]>0):.0%}, val>=.5 {np.mean(G[:,1]>=.5):.0%}, dev>=.5 {np.mean(G[:,0]>=.5):.0%}, median dev {np.median(G[:,0]):.2f}, median val {np.median(G[:,1]):.2f}")
_, _, r = sh(dip(E), E); x = r.net
print(f"  time in market {(r.turn.rolling(5).sum()>0).mean():.0%}")
b = d.ret[E].mean(axis=1).reindex(x.index)
for w in (("1985", "2012"), ("2013", "2018")):
    y, z = x.loc[w[0]:w[1]], b.loc[w[0]:w[1]].fillna(0)
    beta = y.cov(z) / z.var(); alpha = (y - beta * z)
    print(f"  {w}: beta to equities {beta:.2f}, alpha/yr {alpha.mean()*256*100:.2f}%, alpha t {alpha.mean()/alpha.std()*np.sqrt(len(alpha)):.2f}")
