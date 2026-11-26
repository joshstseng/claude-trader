"""Candidate 1 on the VALIDATE window only (2020-2022)."""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, noise, sharpe, span

s = load("QQQ"); a, z = span(s, "val")
P = dict(look=14, every=6, vm=1.0)
r1, t = noise(s, a, z, **P); r2, _ = noise(s, a, z, mult=2.0, **P)
x1, x2 = r1[a:z], r2[a:z]; idx = s.days[a:z]
bh = s.c[a:z, -1] / np.r_[s.prev[a], s.c[a:z - 1, -1]] - 1
eq = np.cumprod(1 + x1)
print(f"VALIDATE {idx[0].date()}..{idx[-1].date()}  trades {t}")
print(f"net {x1.mean()*252*100:.1f}%/yr  Sharpe {sharpe(x1):.2f}  2x cost {x2.mean()*252*100:.1f}%/yr, Sharpe {sharpe(x2):.2f}  max DD {(eq/np.maximum.accumulate(eq)-1).min()*100:.1f}%")
print(f"QQQ buy&hold Sharpe {sharpe(bh):.2f}, corr to QQQ {np.corrcoef(x1, bh)[0,1]:.2f}")
print("by year, %:", (pd.Series(x1, index=idx).groupby(idx.year).sum() * 100).round(1).to_dict(), " QQQ:", (pd.Series(bh, index=idx).groupby(idx.year).sum() * 100).round(1).to_dict())
print("VALIDATE:", "PASS" if x1.sum() > 0 and x2.sum() > 0 else "FAIL")
