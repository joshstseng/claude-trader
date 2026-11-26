"""One look at validation 2020-2022 for candidate EP5 (FROZEN_SCALP.md)."""
import json, numpy as np
from app.research.scalp import lab as S
d = S.load(); side = np.load("data/bars/lab/intraday/scalp_swing_side.npy")
sig = S.filtered(S.ema_signals(d, "5m", "swing"), side)
rows = np.flatnonzero((d.days.year >= 2020) & (d.days.year <= 2022)); W = S.WINDOWS["val"]
base = S.stats(d, S.simulate(d, sig, 3, rows=rows, min_risk=.0015), W)
dbl = S.stats(d, S.simulate(d, sig, 3, rows=rows, min_risk=.0015, cost_bp=1.2, stop_bp=.6), W)
real = S.stats(d, S.simulate(d, sig, 3, rows=rows, min_risk=.0015, cost_bp=.3, stop_bp=.15), W)
bar = {"avg_r>0": base["avg_r"] > 0, "pf>=1.1": base["pf"] >= 1.1, "sharpe>=0.8": base["sharpe"] >= .8,
       "2x costs profitable": dbl["avg_r"] > 0, "2 of 3 years": sum(v > 0 for v in base["years"].values()) >= 2, ">=300 trades": base["trades"] >= 300}
out = {"base": base, "double_costs": dbl, "real_mnq_costs": real, "bar": bar, "pass": all(bar.values())}
json.dump(out, open("app/research/scalp/x4_validate.json", "w"), indent=1, default=float)
for k in ("base", "double_costs", "real_mnq_costs"):
    m = out[k]; print(f"{k:15} trades {m['trades']} avg {m['avg_r']:+.3f}R (gross {m['avg_r_gross']:+.3f}) win {m['win']:.0%} pf {m['pf']:.2f} sharpe {m['sharpe']:.2f} ann {m['ann']*100:.1f}% dd {m['maxdd']*100:.1f}% years {m['years']}")
print(bar, "PASS" if out["pass"] else "FAIL")
