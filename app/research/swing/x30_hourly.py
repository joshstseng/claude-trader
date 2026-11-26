"""Hourly multi-day swing screen on DEV only (2016-2019). No later data is passed to the simulator."""
import itertools

import numpy as np
import pandas as pd

from app.research.swing.hourly import compression, donchian, engine, hourly, pullback, sweep, week_range
from app.research.swing.intraday import COST, Sess, load, sharpe, span


def cut(s, z):
    return Sess(s.sym, s.days[:z], s.o[:z], s.h[:z], s.l[:z], s.c[:z], s.v[:z], s.vol[:z], s.prev[:z])


if __name__ != "__main__":
    raise ImportError("x30 is a script; import cut from hourly_tools instead")

V = {}
for n, k, dr in itertools.product((35, 70, 140), (2., 3., 4.), (0, 1)):
    V[f"hourly channel {n//7}d stop{k} {'long' if dr else 'both'}"] = (donchian, dict(n=n, k=k, direction=dr))
for ma, lw, rr, h in itertools.product((20, 50, 100), (2, 3, 5), (1.5, 2, 3), (21, 35)):
    V[f"trend pullback ma{ma} low{lw} rr{rr} hold{h//7}d"] = (pullback, dict(ma=ma, lows=lw, rr=rr, hold=h))
for kd, rr, h in itertools.product(("nr7", "inside"), (1, 2, 3), (7, 21, 35)):
    V[f"compression {kd} rr{rr} hold{h//7}d"] = (compression, dict(kind=kd, rr=rr, hold=h))
for rr, h, t in itertools.product((1, 2, 3), (7, 14, 35), (False, True)):
    V[f"liquidity sweep rr{rr} hold{h//7}d {'with trend' if t else 'any'}"] = (sweep, dict(rr=rr, hold=h, trend=t))
for rr in (None, 1, 2):
    V[f"Monday range break rr{rr}"] = (week_range, dict(rr=rr))

rows = []
for m in COST:
    full = load(m); a, z = span(full, "dev"); b = hourly(cut(full, z))
    px = b.dcl; bh = np.r_[0, px[1:] / px[:-1] - 1][a:z]
    for name, (fn, p) in V.items():
        sig = fn(b, **p); r1, t = engine(b, *sig); r2, _ = engine(b, *sig, mult=2.0); x, x2 = r1[a:z], r2[a:z]
        y = pd.Series(x, index=b.days[a:z]).groupby(b.days[a:z].year).sum()
        rows.append(dict(market=m, name=name, sharpe=sharpe(x), sharpe2x=sharpe(x2), ret=x.mean() * 252 * 100, trades=t, pos_years=int((y > 0).sum()), bh=sharpe(bh), corr=np.corrcoef(x, bh)[0, 1] if x.std() > 0 else np.nan))
o = pd.DataFrame(rows); o["fam"] = o.name.str.split().str[:2].str.join(" "); o.to_pickle("data/bars/lab/intraday/x30.pkl")
print("trials:", len(o))
print(o.pivot_table(index="fam", columns="market", values="sharpe", aggfunc="max").round(2).to_string())
print("\nmedian Sharpe by family:"); print(o.groupby("fam").sharpe.median().round(2).to_dict())
sl = o[(o.sharpe >= .7) & (o.sharpe2x > .3) & (o.trades >= 60) & (o.pos_years >= 3)].sort_values("sharpe", ascending=False)
print(f"\nShortlist from dev (Sharpe>=.7, 2x-cost Sharpe>.3, 60+ trades, 3+ of 4 years up): {len(sl)}")
print(sl.head(30)[["market", "name", "sharpe", "sharpe2x", "ret", "trades", "pos_years", "bh", "corr"]].round(2).to_string(index=False))
print("\nshortlist count by market and family:"); print(sl.groupby(["market", "fam"]).size().to_string() if len(sl) else "none")
