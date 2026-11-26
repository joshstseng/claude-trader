import json, pandas as pd
from app import settings
from app.research.scalp.post import save_and_post
settings.load_env()
r4 = pd.DataFrame(json.load(open("app/research/scalp/x8_fade.json")))
s = (f"2016–2019 dev only · fade stretches from VWAP while Swing v1 is flat\n\n**{(r4.avg_r>0).sum()} of {len(r4)} positive after costs** · "
     f"{(r4.avg_r_gross>0).sum()} positive before costs · best Sharpe {r4.sharpe.max():.2f} · correlation with Swing ≈ 0\n\n📉 Uncorrelated with Swing, but no edge. Dropped.")
print("run", save_and_post("VWAP fade on quiet days (round 4, dev)", "2016-01-04", "2019-12-31", {"round": 4, "rules": "FROZEN_SCALP.md"}, s,
                           r4.drop(columns="years").round(3).to_csv(index=False)))
s = ("Does the pullback matter? Control = enter at **any** 5-minute close in Swing's direction, same stop and 3R target\n\n"
     "**Dev** EP5 +0.115R · control +0.101R\n**Validation** EP5 +0.101R · control +0.162R\n**Final** EP5 +0.086R · control +0.079R\n"
     "EP5 beats 62% of 200 random Swing-direction entry sets (final)\n\n"
     "📉 **The pullback adds nothing.** EP5's profit is Swing's breakout edge, not a pullback edge.")
print("run", save_and_post("EP5 vs random entries in Swing's direction", "2016-01-04", "2026-10-30", {"control": True, "rules": "FROZEN_SCALP.md"}, s,
                           open("app/research/scalp/x9_control.py").read().join(["```python\n", "\n```"])))
