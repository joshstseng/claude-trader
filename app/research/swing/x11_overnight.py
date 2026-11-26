"""Step 11: the single 2019+ run of the frozen Nasdaq overnight rule."""
import json
import time
import urllib.request as u
from pathlib import Path

import pandas as pd

from app.research.swing.lab import stats

OUT = Path("data/bars/lab/swing/etf")


def get(s):
    f = OUT / f"long_{s}.json"
    if not f.exists():
        r = u.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=725846400&period2={int(time.time())}&interval=1d&events=div%2Csplit", headers={"User-Agent": "Mozilla/5.0"})
        f.write_text(u.urlopen(r, timeout=30).read().decode())
    j = json.loads(f.read_text())["chart"]["result"][0]; q = j["indicators"]["quote"][0]
    adj = j["indicators"].get("adjclose", [{"adjclose": q["close"]}])[0]["adjclose"]
    x = pd.DataFrame({"o": q["open"], "c": q["close"], "a": adj}, index=pd.to_datetime(j["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).normalize()).dropna()
    k = x.a / x.c
    return pd.DataFrame({"o": x.o * k, "c": x.a}).groupby(level=0).last()


x = get("QQQ"); t = get("^IRX").c.reindex(x.index).ffill() / 100 / 252
on = x.o / x.c.shift(1) - 1; hold = x.c.pct_change()
ok = True
for name, a, z in (("HOLDOUT", "2019-01-01", "2024-03-28"), ("FORWARD", "2024-04-01", "2026-11-20")):
    n1, n3, b = [(v - t).loc[a:z].dropna() for v in (on - .0003, on - .0006, hold)]
    s1, s3, sb = stats(n1), stats(n3), stats(b)
    c = [s1["sharpe"] > sb["sharpe"], s1["ret"] > 0, s3["sharpe"] > sb["sharpe"]]; ok &= all(c)
    print(f"{name} {a}..{z}")
    for k, s in (("overnight 1.5bp", s1), ("overnight 3bp", s3), ("QQQ buy & hold", sb)):
        print(f"  {k:<18} ret {s['ret']*100:6.1f}%  vol {s['vol']*100:5.1f}%  Sharpe {s['sharpe']:5.2f}  DD {s['dd']*100:6.1f}%")
    print("  checks:", dict(zip(("sharpe>QQQ", "ret>0", "holds at 3bp"), c)))
    print("  by year overnight/QQQ:", {int(y): (round(((1 + n1[n1.index.year == y]).prod() - 1) * 100, 1), round(((1 + b[b.index.year == y]).prod() - 1) * 100, 1)) for y in sorted(set(n1.index.year))})
print("VERDICT:", "PASS" if ok else "FAIL")
