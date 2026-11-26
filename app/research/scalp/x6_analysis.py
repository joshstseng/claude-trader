"""Information only, after the final test (no rule changes): overlap with Swing, MNQ dollars, concentration."""
import json, numpy as np, pandas as pd
from app.research.scalp import lab as S
from app.research.swing.intraday import load as load5, noise
d = S.load(); side = np.load("data/bars/lab/intraday/scalp_swing_side.npy")
sig = S.filtered(S.ema_signals(d, "5m", "swing"), side)
tr = S.simulate(d, sig, 3, min_risk=.0015)
tr["date"] = d.days[tr.day.to_numpy()]; tr["year"] = tr.date.dt.year
tr["mins"] = tr.out - tr.sig
print("all trades", len(tr), "per day", round(len(tr) / len(d.days), 2), "\nexits", tr.why.value_counts().to_dict())
print("median minutes held", tr.mins.median(), "| long share", round((tr.side > 0).mean(), 2))
print("entry hour (ET):", ((tr.sig + 1) // 60 + 9.5).astype(int).value_counts().sort_index().to_dict())
print("avg R by side:", tr.groupby("side").r.mean().round(3).to_dict())
# MNQ whole contracts, $100k, $500 risk a trade (0.5%), actual MNQ costs: $0.75 fee + 1 tick ($0.50) per side, +1 tick on stops
MULT = 41.0 * 2.0          # QQQ $1 ~ 41 NQ points; $2 per MNQ point
def mnq(t, risk_usd=500):
    n = np.floor(risk_usd / (t.risk_pct * t.entry * MULT))
    pnl = n * MULT * t.side * (t.exit - t.entry) - n * (2 * 1.25 + (t.why == "stop") * .5)
    return n, pnl
tr["contracts"], tr["usd"] = mnq(tr)
for a, z in ((2016, 2019), (2020, 2022), (2023, 2026)):
    t = tr[(tr.year >= a) & (tr.year <= z)]
    days = d.days[(d.days.year >= a) & (d.days.year <= z)]
    daily = pd.Series(0.0, index=days).add(t.groupby("date").usd.sum(), fill_value=0)
    eq = daily.cumsum(); yrs = len(days) / 252
    print(f"MNQ $100k {a}-{z}: ${t.usd.sum():,.0f} total, ${t.usd.sum()/yrs:,.0f}/yr ({t.usd.sum()/yrs/1000:.1f}%/yr), sharpe {daily.mean()/daily.std()*np.sqrt(252):.2f}, worst drop ${(eq-eq.cummax()).min():,.0f}, worst day ${daily.min():,.0f}, contracts median {t.contracts.median():.0f} (0 skipped: {(t.contracts==0).sum()})")
fin = tr[tr.year >= 2023]
byday = fin.groupby("date").r.sum().sort_values(ascending=False)
print("final: top 10 days share of R", round(byday.head(10).sum() / fin.r.sum(), 2), "| without top 10 days avg R/trade", round((fin.r.sum() - byday.head(10).sum()) / len(fin), 3))
# Overlap with Swing v1 (QQQ, 5m research version), daily returns 2016-2026
s5 = load5("QQQ"); i0, i1 = 0, len(s5.days)
v1 = pd.Series(noise(s5, i0, i1, look=14, every=6, vm=1.0)[0][i0:i1], index=s5.days[i0:i1])
ep = pd.Series(0.0, index=d.days).add(tr.groupby("date").r.sum() * .0025, fill_value=0)
j = pd.concat([v1.rename("swing"), ep.rename("ep5")], axis=1).dropna()
for a, z in ((2016, 2019), (2020, 2022), (2023, 2026)):
    x = j[(j.index.year >= a) & (j.index.year <= z)]
    sh = lambda s: s.mean() / s.std() * np.sqrt(252)
    combo = x.swing + x.ep5
    print(f"{a}-{z}: corr {x.swing.corr(x.ep5):.2f} | Swing v1 {x.swing.mean()*252*100:.1f}%/yr Sharpe {sh(x.swing):.2f} | EP5 {x.ep5.mean()*252*100:.1f}%/yr Sharpe {sh(x.ep5):.2f} | together {combo.mean()*252*100:.1f}%/yr Sharpe {sh(combo):.2f}")
tr.to_csv("app/research/scalp/ep5_trades.csv", index=False)
