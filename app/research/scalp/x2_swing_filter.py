"""Round 2 dev grid (2016-2019 only): pullbacks only in Swing v1's direction. FROZEN_SCALP.md round 2."""
import itertools, json, time
import numpy as np, pandas as pd
from app.research.scalp import lab as S
d = S.load(); dev = np.flatnonzero((d.days.year >= 2016) & (d.days.year <= 2019)); W = S.WINDOWS["dev"]
t0 = time.time(); side = S.swing_side(d); print(f"swing side built {time.time()-t0:.0f}s; dev share of minutes long {np.mean(side[dev]>0):.2f} short {np.mean(side[dev]<0):.2f}")
np.save("data/bars/lab/intraday/scalp_swing_side.npy", side)
rows = []
fams = [("vwap", dict(ext=e, tol=t)) for e, t in itertools.product((.0015, .003), (0, .0003))]
fams += [("ema", dict(tf=f, stop=s)) for f, s in itertools.product(("1m", "5m"), ("swing", "ema20"))]
for fam, p in fams:
    sig = S.vwap_signals(d, p["ext"], p["tol"]) if fam == "vwap" else S.ema_signals(d, p["tf"], p["stop"])
    sig = S.filtered(sig, side)
    for x in (1, 1.5, 2, 3, "rule"):
        m = S.stats(d, S.simulate(d, sig, x, "both", "all", rows=dev), W)
        rows.append({"fam": fam, **p, "exit": x, **m})
json.dump(rows, open("app/research/scalp/x2_swing_filter.json", "w"), indent=0, default=float)
x = pd.DataFrame(rows).drop(columns="years"); pd.set_option("display.width", 250)
print(f"positive after costs {(x.avg_r>0).sum()}/40, before costs {(x.avg_r_gross>0).sum()}/40, pass sharpe>=.8&trades>=400: {((x.sharpe>=.8)&(x.trades>=400)).sum()}")
print(x.sort_values("sharpe", ascending=False).round(3).to_string(index=False))
