import json, pandas as pd
from app import settings
from app.research.scalp.post import save_and_post
settings.load_env()
b = pd.DataFrame(json.load(open("app/research/scalp/x23_asia_b.json"))); c = pd.DataFrame(json.load(open("app/research/scalp/x24_asia_c.json")))
b2, b1 = b[b.fam == "B2"], b[b.fam == "B1"]
s = ("Asia session · USD/JPY, AUD/USD, EUR/USD, gold · 2016–2019 dev only\n\n"
     f"**Noise-band breakout (Swing's idea)** · 64 variants · **{(b2.avg_bp_session>0).sum()} positive** · best Sharpe {b2.sharpe.max():.2f}\n"
     f"**First-hour momentum** · 32 variants · **{(b1.avg_bp_session>0).sum()} positive** · best Sharpe {b1.sharpe.max():.2f}\n"
     f"**Fade stretched moves (with the daily trend or not)** · 96 variants · **{(c.avg_bp_session>0).sum()} positive** after costs\n"
     f"-# before costs the fade works (Sharpe up to {c.gross_sharpe.max():.1f} on EUR/USD) but makes ~1 bp a trade; breakeven ≈ 0.4–0.6 bp per side\n\n"
     "📉 **No Asia edge after costs.** Trend-following loses in Asia; reversion is real but too small to pay the spread.")
print("run", save_and_post("Asia trend-following and fades (rounds B–C, dev)", "2016-01-04", "2019-12-31", {"rules": "FROZEN_ASIA.md"}, s,
                           b.drop(columns="years_bp").round(3).to_csv(index=False) + "\n\n" + c.drop(columns="years_bp").round(3).to_csv(index=False)))
