"""Round 4 dev grid (2016-2019 only): VWAP fade while Swing v1 is flat."""
import itertools, json, numpy as np, pandas as pd
from app.research.scalp import lab as S
from app.research.swing.intraday import load as load5, noise
d = S.load(); dev = np.flatnonzero((d.days.year >= 2016) & (d.days.year <= 2019)); W = S.WINDOWS["dev"]
side = np.load("data/bars/lab/intraday/scalp_swing_side.npy")
s5 = load5("QQQ"); v1 = pd.Series(noise(s5, 0, len(s5.days), look=14, every=6, vm=1.0)[0], index=s5.days)
rows = []
for tf, z in itertools.product(("1m", "5m"), (.002, .0035)):
    sig = S.flat_only(S.fade_signals(d, tf, z), side)
    for mr, x in itertools.product((.001, .0015), (1, 2, "rule")):
        tr = S.simulate(d, sig, x, rows=dev, min_risk=mr)
        m = S.stats(d, tr, W)
        ep = pd.Series(0.0, index=d.days[dev]).add(tr.groupby(d.days[tr.day.to_numpy()]).r.sum() * .0025, fill_value=0)
        rows.append({"tf": tf, "z": z, "min_risk": mr, "exit": "vwap" if x == "rule" else x, **m, "corr_swing": float(ep.corr(v1.reindex(ep.index)))})
json.dump(rows, open("app/research/scalp/x8_fade.json", "w"), indent=0, default=float)
x = pd.DataFrame(rows).drop(columns="years"); pd.set_option("display.width", 250)
print(f"positive {(x.avg_r>0).sum()}/24; before costs {(x.avg_r_gross>0).sum()}/24; pass: {((x.sharpe>=.8)&(x.pf>=1.1)&(x.trades>=400)&(x.corr_swing<.3)).sum()}")
print(x.sort_values("sharpe", ascending=False).round(3).to_string(index=False))
