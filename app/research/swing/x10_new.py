"""Step 10: two new families, judged only through 2018. 2019+ is not read here.

A. Overnight drift: hold from the US close to the next US open, flat during US hours, on ETFs that mirror liquid futures.
B. VIX futures premium: short front VIX when the curve is in contango, with risk filters.
"""
import json
import time
import urllib.request as u
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.swing.lab import ROOT, stats

OUT = Path("data/bars/lab/swing/etf"); OUT.mkdir(exist_ok=True)
END = "2018-12-31"


def ohlc(s):
    f = OUT / f"long_{s}.json"
    if not f.exists():
        r = u.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=725846400&period2={int(time.time())}&interval=1d&events=div%2Csplit", headers={"User-Agent": "Mozilla/5.0"})
        f.write_text(u.urlopen(r, timeout=30).read().decode()); time.sleep(.3)
    j = json.loads(f.read_text())["chart"]["result"][0]; q = j["indicators"]["quote"][0]
    x = pd.DataFrame({"o": q["open"], "c": q["close"], "a": j["indicators"]["adjclose"][0]["adjclose"]},
                     index=pd.to_datetime(j["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).normalize()).dropna()
    x = x[(x.o > 0) & (x.c > 0)]; k = x.a / x.c
    return pd.DataFrame({"o": x.o * k, "c": x.a}).groupby(level=0).last().loc[:END]


print("A. Overnight hold, net of 1.5 bp per side (dev to 2012, val 2013-18)")
print(f"{'':<7}{'start':>12}{'on dev':>8}{'on val':>8}{'day dev':>8}{'day val':>8}{'on ret% val':>12}{'on DD val':>10}")
rows = {}
for s in "GLD SLV SPY QQQ IWM DIA TLT IEF USO UNG FXE FXY FXA".split():
    try:
        x = ohlc(s)
    except Exception as e:
        print(s, "ERR", e); continue
    on = x.o / x.c.shift(1) - 1; day = x.c / x.o - 1
    on = on.where(on.abs() < .25); net = on - .0003
    rows[s] = net
    a, b = stats(net.loc[:"2012"]), stats(net.loc["2013":])
    da, db = stats(day.loc[:"2012"]), stats(day.loc["2013":])
    print(f"{s:<7}{str(x.index[0].date()):>12}{a['sharpe']:8.2f}{b['sharpe']:8.2f}{da['sharpe']:8.2f}{db['sharpe']:8.2f}{b['ret']*100:12.1f}{b['dd']*100:10.1f}")

print("\nB. VIX futures, daily, full spread and fees 0.08 pts per side")
base = "https://raw.githubusercontent.com/robcarver17/pysystemtrade/develop/data/futures"
for k, sub in (("adj", "adjusted_prices_csv"), ("mult", "multiple_prices_csv")):
    p = ROOT / k / "VIX.csv"
    if not p.exists():
        p.write_bytes(u.urlopen(f"{base}/{sub}/VIX.csv", timeout=40).read())
A = pd.read_csv(ROOT / "adj/VIX.csv", parse_dates=["DATETIME"], index_col=0).iloc[:, 0]; A = A.groupby(A.index.normalize()).last()
M = pd.read_csv(ROOT / "mult/VIX.csv", parse_dates=["DATETIME"], index_col=0); M = M.groupby(M.index.normalize()).last()
I = A.index; D = A.diff(); px = M.PRICE.reindex(I).ffill(); cr = M.CARRY.reindex(I).ffill()
same = M.CARRY_CONTRACT.reindex(I).ffill() > M.PRICE_CONTRACT.reindex(I).ffill()
slope = ((cr - px) / px).where(same, (px - cr) / px)
spx = pd.read_csv(ROOT / "adj/SP500.csv", parse_dates=["DATETIME"], index_col=0).iloc[:, 0]; spx = spx.groupby(spx.index.normalize()).last().reindex(I).ffill()
up = spx > spx.rolling(200).mean(); v = D.ewm(span=32, min_periods=32).std()
VAR = {"always short": pd.Series(-1.0, index=I), "short if contango": -(slope > 0).astype(float), "short if contango >5%": -(slope > .05).astype(float),
       "contango + S&P>200d": -((slope > 0) & up).astype(float), "contango>5% + S&P>200d": -((slope > .05) & up).astype(float),
       "contango + VIX<25": -((slope > 0) & (px < 25)).astype(float), "contango>5%, S&P>200d, VIX<25": -((slope > .05) & up & (px < 25)).astype(float)}
print(f"{'':<34}{'dev Sh':>8}{'val Sh':>8}{'dev DD':>8}{'val DD':>8}{'val ret':>8}{'worst day':>10}")
for k, sig in VAR.items():
    size = (.10 / 16 / (v / px)).clip(0, .5)  # notional as a fraction of capital, 10% vol target
    h = (sig * size).where(v.notna(), 0).shift(1).fillna(0)  # decided at t, filled at t+1 close
    r = h.shift(1) * D / px.shift(1) - h.diff().abs() * .08 / px
    a, b = stats(r.loc["2005":"2012"]), stats(r.loc["2013":END])
    print(f"{k:<34}{a['sharpe']:8.2f}{b['sharpe']:8.2f}{a['dd']*100:8.1f}{b['dd']*100:8.1f}{b['ret']*100:8.1f}{r.loc[:END].min()*100:10.1f}")
