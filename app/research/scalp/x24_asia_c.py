"""Round C dev grid (2016-2019 only), FROZEN_ASIA.md."""
import itertools, json, time
import pandas as pd
from app.research.scalp import asia as A
W = A.WINDOWS["dev"]; rows = []; t0 = time.time()
for sym in A.COST:
    s = A.sessions(sym)
    for m, tg, sm, flt in itertools.product((1.0, 1.5, 2.0), ("twap", "open"), (.5, 1.0), ("none", "trend")):
        r, n = A.fade_session_returns(s, m, tg, sm, flt)
        g, _ = A.fade_session_returns(s, m, tg, sm, flt, cost_bp=0, stop_bp=0)
        rows.append({"sym": sym, "m": m, "target": tg, "stop": sm, "filter": flt, **A.stats_sess(s, r, n, W), "gross_sharpe": A.stats_sess(s, g, n, W)["sharpe"]})
print(f"{len(rows)} variants in {time.time()-t0:.0f}s")
json.dump(rows, open("app/research/scalp/x24_asia_c.json", "w"), indent=0, default=float)
x = pd.DataFrame(rows); pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(f"positive {(x.avg_bp_session>0).sum()}/96; pass sharpe>=.8&pf>=1.1&trades>=150: {((x.sharpe>=.8)&(x.pf>=1.1)&(x.trades>=150)).sum()}")
print(x.groupby("sym")[["sharpe", "gross_sharpe"]].agg(["mean", "max"]).round(2))
print(x.sort_values("sharpe", ascending=False).head(16).round(3).to_string(index=False))
