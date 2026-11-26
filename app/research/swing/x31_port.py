"""Portfolio view of the two broadest hourly families, using middle settings on all seven markets. DEV only."""
import numpy as np
import pandas as pd

from app.research.swing.hourly import donchian, engine, hourly, pullback
from app.research.swing.intraday import COST, Sess, load, sharpe, span


def cut(s, z):
    return Sess(s.sym, s.days[:z], s.o[:z], s.h[:z], s.l[:z], s.c[:z], s.v[:z], s.vol[:z], s.prev[:z])


C = {"C2 channel 10d, 3 ATR, long only": (donchian, dict(n=70, k=3., direction=1)), "C2b channel 10d, 3 ATR, long+short": (donchian, dict(n=70, k=3., direction=0)),
     "C3 pullback ma100, 3-day, 2R, 5d": (pullback, dict(ma=100, lows=3, rr=2, hold=35))}
spy = load("SPY"); a0, z0 = span(spy, "dev"); sp = pd.Series(spy.c[a0:z0, -1] / np.r_[spy.c[a0, 0], spy.c[a0:z0 - 1, -1]] - 1, index=spy.days[a0:z0])
for name, (fn, p) in C.items():
    R = {}; R2 = {}; T = 0
    for m in COST:
        s = load(m); a, z = span(s, "dev"); b = hourly(cut(s, z)); g = fn(b, **p)
        x, t = engine(b, *g); y, _ = engine(b, *g, mult=2.0); R[m] = pd.Series(x[a:z], index=b.days[a:z]); R2[m] = pd.Series(y[a:z], index=b.days[a:z]); T += t
    P = pd.DataFrame(R).fillna(0).sum(axis=1) / np.sqrt(len(R)) * 1.5; P2 = pd.DataFrame(R2).fillna(0).sum(axis=1) / np.sqrt(len(R)) * 1.5
    j = pd.concat([P, sp], axis=1, join="inner"); e = P.cumsum()
    print(f"{name}\n  dev portfolio {P.mean()*252*100:.1f}%/yr Sharpe {sharpe(P):.2f}, 2x costs {sharpe(P2):.2f}, DD {(e-e.cummax()).min()*100:.1f}%, trades {T}, corr SPY {j.iloc[:,0].corr(j.iloc[:,1]):.2f}, SPY+strategy Sharpe {sharpe(j.sum(axis=1)):.2f} vs SPY {sharpe(j.iloc[:,1]):.2f}")
    print("  by market:", {m: round(sharpe(v), 2) for m, v in R.items()}, " by year %:", (P.groupby(P.index.year).sum() * 100).round(1).to_dict())
