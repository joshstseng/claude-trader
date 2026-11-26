"""Intraday screen on the DEV window only (2016-2019). Validate and final data are never simulated here."""
import itertools
import pickle

import numpy as np
import pandas as pd

from app.research.swing.intraday import COST, gap, late_mom, load, noise, orb, sharpe, span, vwap_trend

V = {}
for n, lo, st, rr in itertools.product((1, 3, 6), (False, True), ("range", "mid"), (None, 2)):
    V[f"ORB {n*5}m {'long' if lo else 'both'} stop={st} rr={rr}"] = (orb, dict(n=n, long_only=lo, stop=st, rr=rr))
for sb, en, th in itertools.product((6, 12), (66, 72), (0, .5)):
    V[f"late momentum sig{sb*5}m entry{en} th{th}"] = (late_mom, dict(sig_bars=sb, entry=en, thresh=th))
for e in (3, 6, 12):
    V[f"VWAP trend every {e*5}m"] = (vwap_trend, dict(every=e))
for k, f in itertools.product((.5, 1, 1.5), (True, False)):
    V[f"gap {'fade' if f else 'go'} k{k}"] = (gap, dict(k=k, fade=f))
for lk, e, vm in itertools.product((14, 30), (6, 12), (1, 1.5)):
    V[f"noise breakout look{lk} every{e*5}m band{vm}"] = (noise, dict(look=lk, every=e, vm=vm))

S = {m: load(m) for m in COST}
rows = []
for m, s in S.items():
    a, z = span(s, "dev")
    bh = np.nan_to_num(s.c[a:z, -1] / np.r_[s.c[a, 0], s.c[a:z - 1, -1]] - 1)
    for k, (fn, p) in V.items():
        r, t = fn(s, a, z, **p); x = r[a:z]
        r2, _ = fn(s, a, z, mult=2.0, **p); x2 = r2[a:z]
        yrs = pd.Series(x, index=s.days[a:z]).groupby(s.days[a:z].year).sum()
        rows.append(dict(market=m, name=k, sharpe=sharpe(x), sharpe2x=sharpe(x2), ret=x.mean() * 252 * 100, trades=t, pos_years=int((yrs > 0).sum()), bh=sharpe(bh), corr=np.corrcoef(x, bh)[0, 1] if x.std() > 0 else np.nan))
o = pd.DataFrame(rows); o.to_pickle("data/bars/lab/intraday/x20.pkl")
print("trials:", len(o), " markets:", list(S), " dev days:", {m: span(s, 'dev')[1] - span(s, 'dev')[0] for m, s in S.items()})
print("\nBest Sharpe by family and market")
o["fam"] = o.name.str.split().str[0]
print(o.pivot_table(index="fam", columns="market", values="sharpe", aggfunc="max").round(2).to_string())
sl = o[(o.sharpe >= .7) & (o.sharpe2x > 0) & (o.trades >= 100) & (o.pos_years >= 3)].sort_values("sharpe", ascending=False)
print(f"\nShortlist from dev (Sharpe>=.7, positive at 2x costs, 100+ trades, 3+ of 4 years up): {len(sl)}")
print(sl.head(30)[["market", "name", "sharpe", "sharpe2x", "ret", "trades", "pos_years", "bh", "corr"]].round(2).to_string(index=False))
