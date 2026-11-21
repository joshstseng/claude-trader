"""Long daily history from Yahoo's public chart endpoint (research holdout), adjusted for splits and dividends.
Cached in data/bars/lab/yahoo/."""

from __future__ import annotations

import gzip
import json
import urllib.request
from datetime import date, datetime, time as dtime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.research.data import D, LAB

NY = ZoneInfo("America/New_York")


def daily(sym: str, start: date = date(1993, 1, 1), end: date = date(2026, 11, 1)) -> list[D]:
    f = LAB / "yahoo" / f"{sym}.json.gz"
    if not f.exists():
        a, z = (int(datetime.combine(x, dtime(0), tzinfo=timezone.utc).timestamp()) for x in (start, end))
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={a}&period2={z}&interval=1d&events=div%2Csplit"
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        r = json.loads(raw)["chart"]["result"][0]
        q, adj = r["indicators"]["quote"][0], r["indicators"]["adjclose"][0]["adjclose"]
        rows = []
        for i, t in enumerate(r["timestamp"]):
            if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i]) or not q["close"][i]:
                continue
            k = adj[i] / q["close"][i]
            rows.append([datetime.fromtimestamp(t, NY).date().isoformat(), q["open"][i] * k, q["high"][i] * k,
                         q["low"][i] * k, adj[i], q["volume"][i] or 0])
        f.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(f, "wt") as fh:
            json.dump(rows, fh)
    with gzip.open(f, "rt") as fh:
        rows = json.load(fh)
    return [D(datetime.combine(date.fromisoformat(r[0]), dtime(0), tzinfo=NY), *r[1:6]) for r in rows]


def market(syms, start: date, end: date):
    raw = {s: {b.t.date(): b for b in daily(s)} for s in syms}
    days = sorted(d for d in set.intersection(*(set(v) for v in raw.values())) if start <= d <= end)
    bars = {s: [raw[s][d] for d in days] for s in syms}
    return SimpleNamespace(dates=days, bars=bars, c={s: [b.c for b in bars[s]] for s in syms})
