"""The daily VIX close for Bumi: Cboe's public history file first, Yahoo as the backup. Only a value dated the
expected session counts as fresh; anything else is reported as stale so Bumi makes no new buys."""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=2y&interval=1d"
LOW, HIGH = 5.0, 200.0


@dataclass
class VixData:
    series: dict[date, float]
    source: str | None
    fresh: bool
    note: str


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _clean(rows: dict[date, float]) -> dict[date, float]:
    return {d: v for d, v in rows.items() if LOW <= v <= HIGH}


def parse_cboe(text: str) -> dict[date, float]:
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            out[datetime.strptime(r["DATE"].strip(), "%m/%d/%Y").date()] = float(r["CLOSE"])
        except (KeyError, ValueError, AttributeError):
            continue
    return _clean(out)


def parse_yahoo(raw: str, today_final: date | None = None) -> dict[date, float]:
    r = json.loads(raw)["chart"]["result"][0]
    out = {}
    for t, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []):
        if c is not None:
            out[datetime.fromtimestamp(t, NY).date()] = float(c)
    return _clean(out)


def fetch(expect: date, cboe=None, yahoo=None) -> VixData:
    """The VIX history, fresh if its last value is dated `expect`. cboe/yahoo: loaders, replaceable in tests."""
    cboe = cboe or (lambda: parse_cboe(_get(CBOE_URL).decode("utf-8", "replace")))
    yahoo = yahoo or (lambda: parse_yahoo(_get(YAHOO_URL).decode("utf-8", "replace")))
    best: dict[date, float] = {}
    best_src, notes = None, []
    for name, load in (("cboe", cboe), ("yahoo", yahoo)):
        try:
            s = load()
        except Exception as e:
            notes.append(f"{name} failed: {type(e).__name__}")
            continue
        if not s:
            notes.append(f"{name} returned nothing")
            continue
        last = max(s)
        if last == expect:
            merged = {**best, **s}
            return VixData(merged, name, True, f"{name}: {s[last]:.2f} on {last}")
        notes.append(f"{name} is stale (last {last})")
        if not best or last > max(best):
            best, best_src = s, name
    return VixData(best, best_src, False, "; ".join(notes))
