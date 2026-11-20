"""Free years of Nasdaq-100 1-minute bars from HistData.com (NSXUSD), for the NQ backtests.

NSXUSD tracks the Nasdaq-100 on futures hours (6 PM to ~4:15 PM ET, Sunday to Friday), so the Asia session
is covered. Prices sit a little off NQ futures (the basis); bands, RSI, ADX and stop distances are relative
moves, so it stands in well for testing. Volume is always 0 (the NQ strategies don't use it).

One zip per year (the current year: one per month), each a CSV of
    20230102 180000;open;high;low;close;0
with times that HistData calls EST, but that actually follow EUROPEAN daylight saving: London time minus
5 hours (UTC−5 in winter, UTC−4 from the last Sunday of March to the last Sunday of October). Checked
2026-11-20: the futures reopen (6 PM New York) shows at 18:00 file time all year except the weeks when
the US and Europe are on different clocks (17:00), and 5m returns line up with Yahoo's NQ only this way.
The download page hands out a token ("tk") that the download form posts back.
Each file is cached (data/bars/futures/histdata/) and only fetched once.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app import paths
from app.strategies.mrs import Bar

PAIR = "NSXUSD"
PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{period}"
GET = "https://www.histdata.com/get.php"
CACHE = paths.SHARED_DATA_DIR / "bars" / "futures" / "histdata"
LONDON = ZoneInfo("Europe/London")
NOTE = "HistData Nasdaq-100 (NSXUSD) 1m → 5m (stands in for NQ)"
UA = {"User-Agent": "Mozilla/5.0"}


def cache_file(period: str, pair: str = PAIR) -> Path:
    return CACHE / pair / f"{period}.json.gz"


def to_utc(stamp: str) -> int:
    """'20250715 180000' (file time) -> unix seconds: file time + 5h is London local time."""
    t = datetime.strptime(stamp, "%Y%m%d %H%M%S") + timedelta(hours=5)
    return int(t.replace(tzinfo=LONDON).timestamp())


def parse_csv(text: str) -> list[list]:
    """CSV lines -> [[unix seconds UTC, o, h, l, c], ...]."""
    out = []
    for line in text.splitlines():
        parts = line.strip().split(";")
        if len(parts) < 5:
            continue
        out.append([to_utc(parts[0]), *(float(x) for x in parts[1:5])])
    return out


def _http(url: str, data: dict | None = None, referer: str | None = None) -> bytes:
    headers = dict(UA, **({"Referer": referer} if referer else {}))
    body = urllib.parse.urlencode(data).encode() if data else None
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=120) as r:
        return r.read()


def fetch_period(period: str, pair: str = PAIR, http=_http) -> list[list]:
    """period = '2023' (a whole year) or '2026/10' (a month of the current year). [] if there's no file."""
    page_url = PAGE.format(pair=pair.lower(), period=period)
    html = http(page_url).decode("utf-8", "replace")
    tk = re.search(r'name="tk" id="tk" value="([^"]+)"', html)
    if not tk:
        return []
    datemonth = period.replace("/", "")
    blob = http(GET, {"tk": tk.group(1), "date": period.split("/")[0], "datemonth": datemonth,
                      "platform": "ASCII", "timeframe": "M1", "fxpair": pair}, referer=page_url)
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return []
    name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
    return parse_csv(z.read(name).decode()) if name else []


def periods(start: date, end: date, today: date | None = None) -> list[str]:
    """Whole years before this year; this year month by month (up to last month)."""
    today = today or date.today()
    out = [str(y) for y in range(start.year, min(end.year, today.year - 1) + 1)]
    if end.year >= today.year:
        first = 1 if start.year < today.year else start.month
        out += [f"{today.year}/{m:02d}" for m in range(first, min(end.month if end.year == today.year else 12,
                                                                today.month - 1) + 1)]
    return out


def download(start: date, end: date, *, pair: str = PAIR, progress=print, http=_http, pause_s: float = 1.0) -> int:
    got = 0
    for p in periods(start, end):
        f = cache_file(p.replace("/", "-"), pair)
        if f.exists():
            continue
        rows = fetch_period(p, pair, http=http)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        with gzip.open(tmp, "wt") as fh:
            json.dump(rows, fh)
        tmp.replace(f)
        progress(f"HistData {pair} {p}: {len(rows):,} minutes")
        got += 1
        if pause_s:
            time.sleep(pause_s)
    return got


def load_1m(start: date, end: date, pair: str = PAIR) -> list[list]:
    lo = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    hi = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    rows = []
    for p in periods(start, end):
        f = cache_file(p.replace("/", "-"), pair)
        if f.exists():
            with gzip.open(f, "rt") as fh:
                rows += [r for r in json.load(fh) if lo <= r[0] < hi]
    rows.sort(key=lambda r: r[0])
    return rows


def bars_5m(start: date, end: date, *, fetch: bool = True, progress=print) -> list[Bar]:
    from app.backtest.dukascopy import to_5m
    if fetch:
        download(start, end, progress=progress)
    return to_5m(load_1m(start, end))
