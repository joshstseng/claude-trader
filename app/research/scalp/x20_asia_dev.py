"""Asia dev grid (2016-2019 only), exactly as FROZEN_ASIA.md."""
import itertools, json
import numpy as np, pandas as pd
from app.research.scalp import asia as A
W = A.WINDOWS["dev"]; rows = []
S = {sym: A.sessions(sym) for sym in A.COST}
for sym, s in S.items():
    dev = np.flatnonzero((s.days.year >= W[0]) & (s.days.year <= W[1]))
    for trend, entry in itertools.product(("d20", "h1"), ("ema", "twap")):
        sig = A.trend_signals(s, trend, entry)
        for mr, x in itertools.product((.0005, .001), (2, 3, "rule")):
            m = A.stats_r(s, A.simulate(s, sig, x, mr, rows=dev), W)
            rows.append({"fam": "T", "sym": sym, "trend": trend, "entry": entry, "min_risk": mr, "exit": x, **m})
fx = []
for sym, sign in (("USDJPY", 1), ("AUDUSD", -1), ("EURUSD", -1)):
    s = S[sym]; got = A.gotobi_days(s.days)
    for kind, days in itertools.product(("pre", "post"), ("all", "gotobi")):
        take = np.ones(len(s.days), bool) if days == "all" else got
        m = A.stats_ret(s, A.session_returns(s, kind, sign), take, W, A.COST[sym])
        fx.append({"fam": "F", "sym": sym, "kind": kind, "days": days, **m})
s = S["XAUUSD"]
for flt in ("all", "d20up"):
    take = np.ones(len(s.days), bool) if flt == "all" else s.d20 > 0
    fx.append({"fam": "G", "sym": "XAUUSD", "kind": "asia", "days": flt, **A.stats_ret(s, A.session_returns(s, "asia"), take, W, A.COST["XAUUSD"])})
json.dump({"T": rows, "FG": fx}, open("app/research/scalp/x20_asia_dev.json", "w"), indent=0, default=float)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
t = pd.DataFrame(rows).drop(columns="years")
print(f"T: {len(t)} variants, positive after costs {(t.avg_r>0).sum()}, before costs {(t.avg_r_gross>0).sum()}, pass sharpe>=.8&pf>=1.1&trades>=200: {((t.sharpe>=.8)&(t.pf>=1.1)&(t.trades>=200)).sum()}")
print(t.groupby("sym")[["avg_r", "avg_r_gross"]].mean().round(3))
print(t.sort_values("sharpe", ascending=False).head(15).round(3).to_string(index=False))
print(pd.DataFrame(fx).drop(columns="years_bp").round(3).to_string(index=False))
for r in fx: print(r["sym"], r["kind"], r["days"], r["years_bp"])
