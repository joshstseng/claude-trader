"""Dev grid (2016-2019 only), exactly as frozen in FROZEN_SCALP.md. Saves every variant."""
import itertools, json, time
import numpy as np
from app.research.scalp import lab as S

d = S.load(); dev = np.flatnonzero((d.days.year >= 2016) & (d.days.year <= 2019)); W = S.WINDOWS["dev"]
rows, t0 = [], time.time()
fams = [("vwap", dict(ext=e, tol=t)) for e, t in itertools.product((.0015, .003), (0, .0003))]
fams += [("ema", dict(tf=f, stop=s)) for f, s in itertools.product(("1m", "5m"), ("swing", "ema20"))]
for fam, p in fams:
    sig = S.vwap_signals(d, p["ext"], p["tol"]) if fam == "vwap" else S.ema_signals(d, p["tf"], p["stop"])
    for x, sides, w in itertools.product((1, 1.5, 2, 3, "rule"), ("both", "long"), ("all", "morning")):
        tr = S.simulate(d, sig, x, sides, w, rows=dev)
        m = S.stats(d, tr, W)
        rows.append({"fam": fam, **p, "exit": x, "sides": sides, "window": w, **{k: (float(v) if not isinstance(v, dict) else v) for k, v in m.items()}})
print(f"{len(rows)} variants in {time.time()-t0:.0f}s")
json.dump(rows, open("app/research/scalp/x1_dev_grid.json", "w"), indent=0)
import pandas as pd
x = pd.DataFrame(rows).drop(columns="years")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
for fam in ("vwap", "ema"):
    y = x[x.fam == fam]
    print(f"\n{fam}: {len(y)} variants, positive avg_r after costs: {(y.avg_r > 0).sum()}, positive before costs: {(y.avg_r_gross > 0).sum()}, sharpe>0.8 with >=400 trades: {((y.sharpe >= .8) & (y.trades >= 400)).sum()}")
    print(y.sort_values("sharpe", ascending=False).head(12).round(3).to_string(index=False))
