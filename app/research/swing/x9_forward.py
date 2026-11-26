"""Step 9: forward check on ETF proxies, 2024-04-01 to 2026-11-20, with the frozen settings."""
import json
import time
import urllib.request as u
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.swing.lab import GROUPS, stats

MAP = {"SP500": "SPY", "NASDAQ": "QQQ", "RUSSELL": "IWM", "DOW": "DIA", "GOLD": "GLD", "SILVER": "SLV", "COPPER": "CPER", "CRUDE_W": "USO", "EUR": "FXE", "GBP": "FXB",
       "AUD": "FXA", "JPY": "FXY", "CAD": "FXC", "CHF": "FXF", "US10": "IEF", "CORN": "CORN", "SOYBEAN": "SOYB", "WHEAT": "WEAT"}
OUT = Path("data/bars/lab/swing/etf"); OUT.mkdir(exist_ok=True)


def get(s):
    f = OUT / f"{s}.json"
    if not f.exists():
        r = u.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=1104537600&period2={int(time.time())}&interval=1d&events=div%2Csplit", headers={"User-Agent": "Mozilla/5.0"})
        f.write_text(u.urlopen(r, timeout=30).read().decode()); time.sleep(.3)
    j = json.loads(f.read_text())["chart"]["result"][0]
    x = j["indicators"].get("adjclose", [{}])[0].get("adjclose") or j["indicators"]["quote"][0]["close"]
    return pd.Series(x, index=pd.to_datetime(j["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).normalize()).dropna().groupby(level=0).last()


P = pd.DataFrame({k: get(v) for k, v in MAP.items()}).loc["2012":"2026-11-20"].ffill(limit=3)
irx = get("^IRX").reindex(P.index).ffill() / 100 / 252
R = P.pct_change(fill_method=None).sub(irx, axis=0)
A = (1 + R.fillna(0)).cumprod().where(P.notna())
V = A.diff().ewm(span=32, min_periods=32).std()
fc = []
for n, sc in ((16, 3.75), (32, 2.65), (64, 1.87)):
    fc.append((((A.ewm(span=n, min_periods=n).mean() - A.ewm(span=4 * n, min_periods=4 * n).mean()) / V) * sc / 10).clip(-2, 2))
F = pd.concat(fc).groupby(level=0).mean()
g = {s: k for k, v in GROUPS.items() for s in v}; by = {}
for s in F.columns: by.setdefault(g[s], []).append(s)
W = pd.Series({s: 1 / len(by) / len(x) for x in by.values() for s in x})[F.columns]
T = (F * (.15 / 16) / (V / A)).mul(W) * 2.0
T = T.clip(-3, 3)
H = T.copy() * np.nan
last = pd.Series(0.0, index=T.columns)
for t, row in T.iterrows():
    ch = (row - last).abs() > .1 * row.abs()
    last = last.where(~ch, row).fillna(0); H.loc[t] = last
pos = H.shift(1).fillna(0)
sleeve = (pos.shift(1) * R.fillna(0)).sum(axis=1) - pos.diff().abs().sum(axis=1) * .0003
a, z = "2024-04-01", "2026-11-20"
s, m, q = sleeve.loc[a:z], R["SP500"].loc[a:z], R["NASDAQ"].loc[a:z]
print("calibration on the 2019-2024/03 holdout (ETF proxy):", {k: round(float(v), 2) for k, v in stats(sleeve.loc['2019':'2024-03-28']).items() if k in ('ret', 'sharpe', 'dd')})
print(f"\nFORWARD {a} to {z} ({len(s)} days), all excess of T-bills")
print(f"{'':<20}{'ret%':>7}{'vol%':>7}{'Sharpe':>8}{'DD%':>8}")
for k, x in (("Trend sleeve", s), ("S&P (SPY)", m), ("S&P + 0.5 trend", m + .5 * s), ("QQQ", q), ("QQQ + 0.5 trend", q + .5 * s)):
    t = stats(x); print(f"{k:<20}{t['ret']*100:7.1f}{t['vol']*100:7.1f}{t['sharpe']:8.2f}{t['dd']*100:8.1f}")
print("sleeve corr to SPY", round(s.corr(m), 2))
print("PASS" if (1 + s).prod() > 1 and stats(m + .5 * s)["sharpe"] >= stats(m)["sharpe"] else "FAIL")
print(pd.DataFrame({"sleeve": s.groupby(s.index.year).apply(lambda v: ((1 + v).prod() - 1) * 100), "SPY": m.groupby(m.index.year).apply(lambda v: ((1 + v).prod() - 1) * 100)}).round(1).to_string())
c = (pos.shift(1) * R.fillna(0)).loc[a:z].sum() * 100
print("\ncontribution by market, % of capital:", c.round(1).sort_values().to_dict())
s.to_pickle(OUT / "forward_sleeve.pkl")
