"""Step 12: Fed-meeting drift and macro regimes, judged through 2018 only."""
import json
import re
import time
import urllib.request as u
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.swing.lab import load, stats

MAC = Path("data/bars/lab/swing/macro"); ETF = Path("data/bars/lab/swing/etf")
MN = "January February March April May June July August September October November December".split()


def page(y):
    f = MAC / f"fomc_{y}.html"
    if not f.exists():
        r = u.Request(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm", headers={"User-Agent": "Mozilla/5.0"})
        f.write_bytes(u.urlopen(r, timeout=30).read()); time.sleep(.25)
    return f.read_text(errors="ignore")


D = []
for y in range(1994, 2021):
    for m, days in re.findall(r"(" + "|".join(MN) + r")(?:/(?:" + "|".join(MN) + r"))?\s+([0-9]{1,2}(?:-[0-9]{1,2})?)\s+Meeting", page(y)):
        D.append(pd.Timestamp(y, MN.index(m) + 1, int(days.split("-")[-1])))
FOMC = pd.DatetimeIndex(sorted(set(D)))
print("FOMC dates through 2020:", len(FOMC), FOMC[0].date(), FOMC[-1].date(), "per year", round(len(FOMC) / 27, 1))
d = load(); I = d.adj.index; END = "2018-12-31"
on = pd.Series(I.isin(FOMC), index=I).astype(float)
pre = pd.Series(I.isin(FOMC), index=I).shift(-1).fillna(False).astype(float)
post = pd.Series(I.isin(FOMC), index=I).shift(1).fillna(False).astype(float)
rows = []


def event(s, mask, sign=1.0):
    vol = d.ret[s].ewm(span=32, min_periods=32).std().shift(2)
    size = (.01 / vol).clip(0, 3)
    r = sign * mask * size * d.ret[s] - mask * size * 2 * (d.cost[s] / d.price[s])
    return r.loc[:END]


for s in ("SP500", "NASDAQ", "DOW", "SP400", "US10", "US5", "US30", "GOLD", "SILVER", "EUR", "JPY", "CRUDE_W"):
    for nm, mask in (("FOMC day", on), ("day before", pre), ("day after", post), ("FOMC day+before", (on + pre).clip(0, 1))):
        r = event(s, mask)
        x, y = r.loc["1994":"2012"], r.loc["2013":END]
        rows.append(dict(name=f"{nm} {s}", dev=x.mean() / x.std() * 16, val=y.mean() / y.std() * 16, dev_ret=x.sum() / (len(x) / 256) * 100, val_ret=y.sum() / (len(y) / 256) * 100))


def yh(s):
    f = ETF / f"long_{s}.json"
    if not f.exists():
        r = u.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=725846400&period2={int(time.time())}&interval=1d", headers={"User-Agent": "Mozilla/5.0"})
        f.write_text(u.urlopen(r, timeout=30).read().decode()); time.sleep(.25)
    j = json.loads(f.read_text())["chart"]["result"][0]
    return pd.Series(j["indicators"]["quote"][0]["close"], index=pd.to_datetime(j["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).normalize()).dropna().groupby(level=0).last().reindex(I).ffill(limit=5)


t10, t3, vix = yh("^TNX"), yh("^IRX"), yh("^VIX")
curve = t10 - t3; REG = {"curve>0": curve > 0, "curve steepening 60d": curve > curve.shift(60), "yields falling 60d": t10 < t10.shift(60), "VIX<20": vix < 20, "VIX falling 20d": vix < vix.rolling(20).mean(),
                         "VIX<20 & curve>0": (vix < 20) & (curve > 0)}
for k, g in REG.items():
    for s in ("SP500", "NASDAQ", "US10", "GOLD"):
        sig = g.astype(float).where(g.notna()).shift(2).fillna(0)
        vol = d.ret[s].ewm(span=32, min_periods=32).std().shift(2); size = (.15 / 16 / vol).clip(0, 2)
        h = sig * size; r = (h * d.ret[s] - h.diff().abs() * d.cost[s] / d.price[s]).loc[:END]
        bh = (size * d.ret[s]).loc[:END]
        x, y = r.loc["1994":"2012"], r.loc["2013":END]
        rows.append(dict(name=f"regime {k} long {s}", dev=x.mean() / x.std() * 16, val=y.mean() / y.std() * 16, dev_ret=x.sum() / (len(x) / 256) * 100, val_ret=y.sum() / (len(y) / 256) * 100,
                         bh_dev=bh.loc["1994":"2012"].mean() / bh.loc["1994":"2012"].std() * 16, bh_val=bh.loc["2013":].mean() / bh.loc["2013":].std() * 16))
o = pd.DataFrame(rows).set_index("name"); o["worst"] = o[["dev", "val"]].min(axis=1)
print("trials:", len(o), "passed (Sharpe>=.5 both):", int((o.worst >= .5).sum()))
print(o.sort_values("worst", ascending=False).head(16).round(2).to_string())
