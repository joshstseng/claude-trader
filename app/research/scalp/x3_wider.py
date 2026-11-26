"""Round 3 dev grid (2016-2019 only). FROZEN_SCALP.md round 3."""
import itertools, json
import numpy as np, pandas as pd
from app.research.scalp import lab as S
d = S.load(); dev = np.flatnonzero((d.days.year >= 2016) & (d.days.year <= 2019)); W = S.WINDOWS["dev"]
side = np.load("data/bars/lab/intraday/scalp_swing_side.npy")
rows = []
for tf, stop in itertools.product(("5m", "15m"), ("swing", "ema20")):
    sig = S.filtered(S.ema_signals(d, tf, stop), side)
    for mr, x in itertools.product((.0006, .001, .0015), (2, 3, "rule")):
        m = S.stats(d, S.simulate(d, sig, x, rows=dev, min_risk=mr), W)
        real = S.stats(d, S.simulate(d, sig, x, rows=dev, min_risk=mr, cost_bp=.3, stop_bp=.15), W)
        rows.append({"tf": tf, "stop": stop, "min_risk": mr, "exit": x, **m, "real_avg_r": real["avg_r"], "real_sharpe": real["sharpe"]})
json.dump(rows, open("app/research/scalp/x3_wider.json", "w"), indent=0, default=float)
x = pd.DataFrame(rows).drop(columns="years"); pd.set_option("display.width", 250)
print(f"positive {(x.avg_r>0).sum()}/36; pass sharpe>=.8&pf>=1.1&trades>=400: {((x.sharpe>=.8)&(x.pf>=1.1)&(x.trades>=400)).sum()}")
print(x.sort_values("sharpe", ascending=False).round(3).to_string(index=False))
