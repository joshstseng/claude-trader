"""One look at validation 2020-2022 for USD/JPY pre-fix on gotobi days (FROZEN_ASIA.md)."""
import json, numpy as np
from app.research.scalp import asia as A
s = A.sessions("USDJPY"); g = A.gotobi_days(s.days); r = A.session_returns(s, "pre", 1); W = A.WINDOWS["val"]
base = A.stats_ret(s, r, g, W, .5); dbl = A.stats_ret(s, r, g, W, 1.0); allday = A.stats_ret(s, r, np.ones(len(r), bool), W, .5)
bar = {"avg>0": base["avg_bp"] > 0, "pf>=1.1": base["pf"] >= 1.1, "sharpe>=0.8": base["sharpe"] >= .8, "2x costs": dbl["avg_bp"] > 0,
       "2 of 3 years": sum(v > 0 for v in base["years_bp"].values()) >= 2, ">=80 trades": base["trades"] >= 80}
json.dump({"base": base, "double": dbl, "all_days_info": allday, "bar": bar}, open("app/research/scalp/x21_gotobi_val.json", "w"), indent=1, default=float)
for k, m in (("gotobi", base), ("double costs", dbl), ("all days (info)", allday)):
    print(f"{k:16} trades {m['trades']} avg {m['avg_bp']:+.2f}bp win {m['win']:.0%} pf {m['pf']:.2f} sharpe {m['sharpe']:.2f} years {m['years_bp']}")
print(bar, "PASS" if all(bar.values()) else "FAIL")
