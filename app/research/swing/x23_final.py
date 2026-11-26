"""The single FINAL-window run of candidate 1 against the rules in FROZEN_INTRADAY.md."""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, noise, sharpe, span
from app.research.swing.x22_audit import rewrite

s, spy = load("QQQ"), load("SPY"); a, z = span(s, "final")
r1, t = noise(s, a, z, look=14, every=6, vm=1.0); r2, _ = noise(s, a, z, look=14, every=6, vm=1.0, mult=2.0)
idx = s.days[a:z]; x = pd.Series(r1[a:z], index=idx); x2 = pd.Series(r2[a:z], index=idx)
bh = pd.Series(s.c[a:z, -1] / np.r_[s.prev[a], s.c[a:z - 1, -1]] - 1, index=idx)
sa, sz = span(spy, "final"); sp = pd.Series(spy.c[sa:sz, -1] / np.r_[spy.prev[sa], spy.c[sa:sz - 1, -1]] - 1, index=spy.days[sa:sz])
j = pd.concat([x, sp], axis=1, join="inner"); j.columns = ["x", "s"]
va, vz = span(s, "val"); val = noise(s, va, vz, look=14, every=6, vm=1.0)[0][va:vz]
yr = x.groupby(x.index.year).sum(); eq = (1 + x).cumprod()
share = yr.max() / x.sum() if x.sum() > 0 else np.inf
C = [("1 Sharpe>=.7 and profit>0", sharpe(x) >= .7 and x.sum() > 0), ("2 profit>0 at 2x costs", x2.sum() > 0), ("3 100+ trades", t >= 100), ("4 3+ of 4 years up", (yr > 0).sum() >= 3),
     ("5 no year >60% of profit", share <= .6), ("6 beats QQQ Sharpe, or corr<.3 and improves SPY", sharpe(x) > sharpe(bh) or (j.x.corr(j.s) < .3 and sharpe(j.s + j.x) > sharpe(j.s))), ("7 made money in validate", val.sum() > 0)]
print(f"FINAL {idx[0].date()}..{idx[-1].date()}  {len(x)} sessions, {t} trades")
print(f"net {x.mean()*252*100:.1f}%/yr  Sharpe {sharpe(x):.2f}  max DD {(eq/eq.cummax()-1).min()*100:.1f}%  | 2x costs {x2.mean()*252*100:.1f}%/yr, Sharpe {sharpe(x2):.2f}")
print(f"QQQ Sharpe {sharpe(bh):.2f}, return {bh.mean()*252*100:.1f}%/yr  | SPY Sharpe {sharpe(j.s):.2f} | corr to SPY {j.x.corr(j.s):.2f}, to QQQ {x.corr(bh):.2f}")
print(f"SPY + strategy: {(j.s+j.x).mean()*252*100:.1f}%/yr, Sharpe {sharpe(j.s+j.x):.2f}, max DD {(((1+j.s+j.x).cumprod()/(1+j.s+j.x).cumprod().cummax())-1).min()*100:.1f}% vs SPY {(((1+j.s).cumprod()/(1+j.s).cumprod().cummax())-1).min()*100:.1f}%")
print("by year, % strategy:", (yr * 100).round(1).to_dict(), "| QQQ:", (bh.groupby(bh.index.year).sum() * 100).round(1).to_dict())
for k, v in C:
    print(("PASS " if v else "FAIL ") + k)
print("VERDICT:", "PASS" if all(v for _, v in C) else "FAIL")
print("\nSensitivity (reported, not used to choose anything)")
for d, b in ((2, .6), (3, .6), (1, 1.5), (1, 3.0), (2, 1.5)):
    y = rewrite(s, a, z, d, b)[a:z]; print(f"  fill delay {(d-1)*5:>2} min, {b} bp/side: {y.mean()*252*100:6.2f}%/yr  Sharpe {sharpe(y):5.2f}")
o = x.sort_values(ascending=False); print(f"top 10 days = {o.head(10).sum()/o.sum():.0%} of profit; without them {o.iloc[10:].mean()*252*100:.1f}%/yr")
print(f"win days {(x[x!=0]>0).mean():.0%}, average win {x[x>0].mean()*100:.2f}%, average loss {x[x<0].mean()*100:.2f}%")
