import json, pandas as pd
from app import settings
from app.research.scalp.post import save_and_post
settings.load_env()
x = pd.DataFrame(json.load(open("app/research/scalp/x11_spy_dev_grid.json")))
v, e = x[x.fam == "vwap"], x[x.fam == "ema"]
s = (f"Same 160-variant grid as #80, on **SPY** 1-minute · 2016–2019 dev only\n\n"
     f"**VWAP pullback** · {(v.avg_r>0).sum()} of 80 positive · best Sharpe {v.sharpe.max():.2f} (only {int(v.loc[v.sharpe.idxmax(),'trades'])} trades)\n"
     f"**EMA 9/20 pullback** · {(e.avg_r>0).sum()} of 80 positive · best Sharpe {e.sharpe.max():.2f}\n\n📉 **0 of 160 clear the bar.** The QQQ result isn't market-specific.")
print("run", save_and_post("SPY check of the pullback grid (dev)", "2016-01-04", "2019-12-31", {"market": "SPY", "rules": "FROZEN_SCALP.md"}, s,
                           x.drop(columns="years").round(3).to_csv(index=False)))
