import json, pandas as pd
from app import settings
from app.research.scalp.post import save_and_post
settings.load_env()
d = json.load(open("app/research/scalp/x20_asia_dev.json")); t = pd.DataFrame(d["T"]); fg = pd.DataFrame(d["FG"])
g = fg[(fg.sym == "USDJPY") & (fg.kind == "pre") & (fg.days == "gotobi")].iloc[0]
s = ("Asia session 9:00–17:00 Tokyo · USD/JPY, AUD/USD, EUR/USD, gold · HistData 1-minute · 2016–2019 dev only\n\n"
     f"**Trend pullbacks** (EMA 9/20 or TWAP, daily or 1h trend) · 96 variants · **{(t.avg_r>0).sum()} positive** · best Sharpe {t.sharpe.max():.2f}\n"
     f"**Tokyo fix trades** · 12 variants · only USD/JPY on gotobi days works: {g.avg_bp:+.2f} bp · PF {g.pf:.2f} · Sharpe {g.sharpe:.2f}\n"
     "**Gold Asian-hours drift** · 2 variants · both negative\n\n-# Fixed a clock bug first: HistData is New York time with daylight saving")
print("run", save_and_post("Asia session dev grid (110 variants)", "2016-01-04", "2019-12-31", {"rules": "FROZEN_ASIA.md"}, s,
                           t.drop(columns="years").round(3).to_csv(index=False) + "\n\n" + fg.drop(columns="years_bp").round(3).to_csv(index=False)))
v = json.load(open("app/research/scalp/x21_gotobi_val.json"))
s = (f"USD/JPY · buy 9:00 Tokyo, sell 9:54 · gotobi days only · one look at 2020–2022\n\n**{v['base']['trades']} trades · {v['base']['avg_bp']:+.2f} bp · PF {v['base']['pf']:.2f} · Sharpe {v['base']['sharpe']:.2f}**\n"
     + " · ".join(f"{y}: {x:+d} bp" for y, x in v["base"]["years_bp"].items()) + "\n\n📉 **Fails validation.** The 2016–2019 effect (+1.45 bp, Sharpe 0.86) didn't last. Final window not looked at.")
print("run", save_and_post("Gotobi fix trade, validation", "2020-01-01", "2022-12-31", {"rules": "FROZEN_ASIA.md"}, s, "```json\n" + json.dumps(v, indent=1) + "\n```"))
