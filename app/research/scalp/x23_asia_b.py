"""Round B dev grid (2016-2019 only), FROZEN_ASIA.md."""
import itertools, json, time
import pandas as pd
from app.research.scalp import asia as A
W = A.WINDOWS["dev"]; rows = []; t0 = time.time()
for sym in A.COST:
    s = A.sessions(sym)
    for m, chk, ex, flt in itertools.product((1.0, 1.5), (30, 60), ("band", "twap"), ("none", "d20")):
        r, n = A.band_session_returns(s, m, chk, ex, flt)
        rows.append({"fam": "B2", "sym": sym, "m": m, "chk": chk, "exit": ex, "filter": flt, **A.stats_sess(s, r, n, W)})
    for k, ex, flt in itertools.product((.5, 1.0), ("close", "stop"), ("none", "d20")):
        r, n = A.momentum_session_returns(s, k, ex, flt)
        rows.append({"fam": "B1", "sym": sym, "k": k, "exit": ex, "filter": flt, **A.stats_sess(s, r, n, W)})
print(f"{len(rows)} variants in {time.time()-t0:.0f}s")
json.dump(rows, open("app/research/scalp/x23_asia_b.json", "w"), indent=0, default=float)
x = pd.DataFrame(rows); pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
for fam in ("B2", "B1"):
    y = x[x.fam == fam]
    print(f"\n{fam}: positive {(y.avg_bp_session>0).sum()}/{len(y)}; pass sharpe>=.8&pf>=1.1&trades>=150: {((y.sharpe>=.8)&(y.pf>=1.1)&(y.trades>=150)).sum()}")
    print(y.groupby("sym").sharpe.agg(["mean", "max"]).round(2))
    print(y.sort_values("sharpe", ascending=False).head(8).drop(columns="years_bp").round(3).to_string(index=False))
