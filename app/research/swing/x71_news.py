"""Swing v1 on red-folder days, following FROZEN_V1X.md."""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, sharpe
from app.research.swing.news_dates import calendar
from app.research.swing.v1x import X, bands, gates, rng, run, vwap

s = load("QQQ"); U, D, VW = (*bands(s), vwap(s)); C = calendar()
print("dates per year:"); print(pd.DataFrame({k: pd.Series(v.year).value_counts().sort_index() for k, v in C.items()}).fillna(0).astype(int).loc[2016:2026].T.to_string())
M = {k: s.days.isin(v) for k, v in C.items()}; ALL = np.logical_or.reduce(list(M.values()))
print("trading days matched:", {k: int(v.sum()) for k, v in M.items()}, "any:", int(ALL.sum()), f"({ALL.mean():.0%} of days)")
fomc_bar = np.where(M["FOMC"], 54, -1)
cands = [(f"Skip {k} days", X(), dict(skip=v)) for k, v in M.items()]
cands += [("Skip all red-folder days", X(), dict(skip=ALL)), ("Skip CPI + NFP days", X(), dict(skip=M["CPI"] | M["NFP"])), ("Skip CPI + NFP + FOMC", X(), dict(skip=M["CPI"] | M["NFP"] | M["FOMC"])), ("FOMC days: flat until 2 PM release", X(), dict(start_bar=fomc_bar))]
gates(s, "RED-FOLDER NEWS", cands, U, D, VW)
print("\nWhere v1's profit comes from (attribution only, nothing is chosen from this)")
for lab, a0, z0 in (("2016-19", "2016", "2019"), ("2020-22", "2020", "2022"), ("2023-Oct26", "2023", "2026")):
    a, z = int(s.days.searchsorted(pd.Timestamp(a0 + "-01-01"))), int(s.days.searchsorted(pd.Timestamp(z0 + "-12-31"), side="right")); r = run(s, X(), a, z, U, D, VW)[0]; x = r[a:z]
    print(f" {lab}: normal days {x[~ALL[a:z]].mean()*1e4:5.1f} bp/day over {(~ALL[a:z]).sum()} days")
    for k, m in {**M, "Any red": ALL}.items():
        y = x[m[a:z]]; print(f"   {k:<8} {len(y):3d} days  avg {y.mean()*1e4:6.1f} bp  total {y.sum()*100:5.1f}%  share of profit {y.sum()/x.sum():5.0%}  win days {(y[y!=0]>0).mean():.0%}")
