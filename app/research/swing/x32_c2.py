"""Candidate 2: validate gate, then the single final run only if the gate passes."""
import numpy as np
import pandas as pd

from app.research.swing.hourly import donchian, engine, hourly
from app.research.swing.intraday import COST, Sess, load, sharpe, span

P = dict(n=70, k=3., direction=1)
D = {m: load(m) for m in COST}


def cut(s, z):
    return Sess(s.sym, s.days[:z], s.o[:z], s.h[:z], s.l[:z], s.c[:z], s.v[:z], s.vol[:z], s.prev[:z])


def port(w, mult=1.0):
    R, T = {}, 0
    for m, s in D.items():
        a, z = span(s, w); b = hourly(cut(s, z)); g = donchian(b, **P); x, _ = engine(b, *g, mult=mult)
        R[m] = pd.Series(x[a:z], index=b.days[a:z]); T += int((np.diff(np.r_[0, (g[0] != 0).astype(int)]) == 1)[np.searchsorted(b.day, a):].sum())
    X = pd.DataFrame(R).fillna(0)
    return X.sum(axis=1) * 1.5 / np.sqrt(len(R)), X


def trades(w):
    n = 0
    for m, s in D.items():
        a, z = span(s, w); b = hourly(cut(s, z)); g = donchian(b, **P)
        start = int(np.searchsorted(b.day, a)); h = b
        import app.research.swing.hourly as hh
        c = hh.H(h.sym, h.days[a:], h.day[start:] - a, h.o[start:], h.h[start:], h.l[start:], h.c[start:], h.atr[start:], h.dhi[a:], h.dlo[a:], h.dcl[a:], h.dop[a:], h.dday[a:] - a)
        n += engine(c, g[0][start:], g[1][start:], g[2][start:], g[3][start:], g[4][start:])[1]
    return n


def line(k, x):
    e = x.cumsum(); print(f"{k:<26}{x.mean()*252*100:6.1f}%/yr  Sharpe {sharpe(x):5.2f}  max DD {(e-e.cummax()).min()*100:6.1f}%")


v1, vm = port("val"); v2, _ = port("val", 2.0)
print("VALIDATE 2020-2022"); line("1x costs", v1); line("2x costs", v2)
print("  by year %:", (v1.groupby(v1.index.year).sum() * 100).round(1).to_dict(), " by market Sharpe:", {m: round(sharpe(vm[m]), 2) for m in vm})
if not (v1.sum() > 0 and v2.sum() > 0):
    print("VALIDATE: FAIL. The final window was not run."); raise SystemExit
print("VALIDATE: PASS")
x, xm = port("final"); x2, _ = port("final", 2.0); t = trades("final")
sp = load("SPY"); a, z = span(sp, "final"); s = pd.Series(sp.c[a:z, -1] / np.r_[sp.prev[a], sp.c[a:z - 1, -1]] - 1, index=sp.days[a:z])
j = pd.concat([x, s], axis=1, join="inner"); j.columns = ["x", "s"]; y = x.groupby(x.index.year).sum(); share = y.max() / x.sum() if x.sum() > 0 else np.inf
C = [("1 Sharpe>=.7 and profit>0", sharpe(x) >= .7 and x.sum() > 0), ("2 profit>0 at 2x costs", x2.sum() > 0), ("3 100+ trades", t >= 100), ("4 3+ of 4 years up", (y > 0).sum() >= 3), ("5 no year >60% of profit", share <= .6),
     ("6 corr to SPY<.3 and improves SPY", j.x.corr(j.s) < .3 and sharpe(j.x + j.s) > sharpe(j.s)), ("7 made money in validate", v1.sum() > 0)]
print("\nFINAL 2023-Oct 2026, trades", t); line("1x costs", x); line("2x costs", x2); line("SPY", s); line("SPY + strategy", j.x + j.s)
print(f"corr to SPY {j.x.corr(j.s):.2f}\nby year %: {(y*100).round(1).to_dict()}\nby market Sharpe: { {m: round(sharpe(xm[m]), 2) for m in xm} }")
for k, ok in C:
    print(("PASS " if ok else "FAIL ") + k)
print("VERDICT:", "PASS" if all(ok for _, ok in C) else "FAIL")
