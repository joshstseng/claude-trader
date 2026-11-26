import json
import pandas as pd
from app import settings
from app.research.scalp.post import save_and_post
settings.load_env()
x = pd.DataFrame(json.load(open("app/research/scalp/x1_dev_grid.json")))
def tag(r):
    return (f"VWAP ext {r.ext*100:.2f}% tol {r.tol*100:.2f}%" if r.fam == "vwap" else f"EMA {r.tf} stop {r.stop}") + f" · exit {r.exit} · {r.sides} · {r.window}"
lines = []
for fam, name in (("vwap", "VWAP pullback"), ("ema", "EMA 9/20 pullback")):
    y = x[x.fam == fam]; b = y.sort_values("sharpe", ascending=False).iloc[0]
    lines.append(f"**{name}** · {len(y)} variants · **{(y.avg_r > 0).sum()} positive after costs** · {(y.avg_r_gross > 0).sum()} positive before costs\n"
                 f"-# best: {tag(b)} · {int(b.trades)} trades · {b.avg_r:+.3f}R · Sharpe {b.sharpe:.2f}")
summary = ("2016–2019 dev window only · QQQ 1-minute · 0.6 bp per side + 0.3 bp on stops\n\n" + "\n".join(lines) +
           "\n\n📉 **No variant clears the bar.** Gross edge ≈ +0.05 to +0.10R a trade, costs ≈ 0.1R.")
md = ("Rules: app/research/scalp/FROZEN_SCALP.md\n\n| Variant | Trades | Avg R | Avg R before costs | Win | PF | Sharpe | Per day |\n|---|---|---|---|---|---|---|---|\n" +
      "\n".join(f"| {tag(r)} | {int(r.trades)} | {r.avg_r:+.3f} | {r.avg_r_gross:+.3f} | {r.win:.0%} | {r.pf:.2f} | {r.sharpe:.2f} | {r.per_day:.2f} |"
                for r in x.sort_values("sharpe", ascending=False).itertuples()))
print("run", save_and_post("VWAP & EMA pullback dev grid (160 variants)", "2016-01-04", "2019-12-31",
                           {"grid": "x1_dev_grid", "rules": "FROZEN_SCALP.md"}, summary, md))
