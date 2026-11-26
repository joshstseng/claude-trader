import json, pandas as pd
from app import settings
from app.research.scalp.post import save_and_post
settings.load_env()
r2 = pd.DataFrame(json.load(open("app/research/scalp/x2_swing_filter.json"))); r3 = pd.DataFrame(json.load(open("app/research/scalp/x3_wider.json")))
s = ("2016–2019 dev only · pullbacks taken only in Swing v1's direction\n\n"
     f"**Round 2** (same rules + Swing filter) · 40 variants · **{(r2.avg_r>0).sum()} positive** · best Sharpe {r2.sharpe.max():.2f}\n"
     f"**Round 3** (EMA only, wider minimum stops) · 36 variants · **{(r3.avg_r>0).sum()} positive** · {((r3.sharpe>=.8)&(r3.pf>=1.1)&(r3.trades>=400)).sum()} clear the bar\n\n"
     "✅ Chosen: **EP5** · 5m EMA 9/20 pullback · Swing direction · swing-low stop ≥0.15% · 3R target\n-# dev: 573 trades · +0.115R · PF 1.21 · Sharpe 0.91")
md = "## Round 2 (csv)\n\n" + r2.drop(columns="years").round(3).to_csv(index=False) + "\n\n## Round 3\n\n" + r3.drop(columns="years").round(3).to_csv(index=False)
print("run", save_and_post("Pullbacks in Swing's direction (rounds 2–3, dev)", "2016-01-04", "2019-12-31", {"rounds": [2, 3], "rules": "FROZEN_SCALP.md"}, s, md))
v = json.load(open("app/research/scalp/x4_validate.json")); f = json.load(open("app/research/scalp/x5_final.json"))
def line(name, m): return f"**{name}** · {m['trades']} trades · **{m['avg_r']:+.3f}R** · PF {m['pf']:.2f} · Sharpe {m['sharpe']:.2f} · " + " · ".join(f"{y}: {x:+.0f}R" for y, x in m["years"].items())
s = ("EP5 · one look at each window, rules unchanged · 0.25% risk a trade\n\n" + line("Validation 2020–22", v["base"]) + "\n" + line("Final 2023–Oct 26", f["base"]) +
     f"\n-# double costs: {v['double_costs']['avg_r']:+.3f}R / {f['double_costs']['avg_r']:+.3f}R · actual MNQ costs: {v['real_mnq_costs']['avg_r']:+.3f}R / {f['real_mnq_costs']['avg_r']:+.3f}R\n\n"
     "✅ Passes the pre-set bar in both windows (final Sharpe 0.81 vs 0.80 needed)\n"
     "⚠️ But: **correlation 0.6–0.7 with Swing v1**, weaker than Swing (3.4% vs 9.3%/yr final), top 10 days = 86% of final profit, median hold 85 min")
md = "```json\n" + json.dumps({"validation": v, "final": f}, indent=1, default=float) + "\n```"
print("run", save_and_post("EP5 validation + final test", "2020-01-02", "2026-10-30", {"candidate": "EP5", "rules": "FROZEN_SCALP.md"}, s, md))
