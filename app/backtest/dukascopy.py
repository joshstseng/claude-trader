"""Free years of Nasdaq-100 1-minute bars from Dukascopy's public data feed, for Mr. S's backtests.

The instrument is Dukascopy's Nasdaq-100 CFD (USATECHIDXUSD): it tracks the cash index, so its prices sit a
little off NQ futures (the basis), but it trades nearly around the clock like NQ, including the Asia session.
Bands, RSI, ADX and stop distances are all relative moves, so it stands in well for testing; volume isn't
real exchange volume (Mr. S doesn't use it).

One file per UTC day: .../USATECHIDXUSD/<year>/<month 0-based>/<day>/BID_candles_min_1.bi5, LZMA-compressed
24-byte records (seconds into the day, open, close, low, high as integers / 1000, volume as a float).
Each day is cached (data/bars/futures/dukascopy/), so a download can stop and pick up where it left off.
The feed throttles: one day at a time, a short pause between, and backing off on errors.
"""

from __future__ import annotations

import gzip
import json
import lzma
import struct
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import paths
from app.strategies.mrs import Bar

SYMBOL = "USATECHIDXUSD"
SCALE = 1000.0
URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
CACHE = paths.SHARED_DATA_DIR / "bars" / "futures" / "dukascopy"
NOTE = "Dukascopy Nasdaq-100 CFD 1m → 5m (stands in for NQ)"


def day_file(sym: str, day: date) -> Path:
    return CACHE / sym / f"{day.isoformat()}.json.gz"


def parse(raw: bytes, day: date) -> list[list]:
    """-> [[unix seconds, o, h, l, c], ...] for minutes that traded (flat, zero-volume minutes dropped)."""
    if not raw:
        return []
    data = lzma.decompress(raw)
    base = int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    out = []
    for k in range(len(data) // 24):
        t, o, c, l, h, v = struct.unpack(">5if", data[k * 24:(k + 1) * 24])
        if v <= 0 and o == c == l == h:
            continue
        out.append([base + t, o / SCALE, h / SCALE, l / SCALE, c / SCALE])
    return out


def fetch_day(sym: str, day: date, tries: int = 8, opener=None) -> list[list]:
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day)
    opener = opener or (lambda u: urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
    wait = 2.0
    for k in range(tries):
        try:
            return parse(opener(url), day)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            err = e
        except Exception as e:  # noqa: BLE001 - timeouts, resets: retry
            err = e
        time.sleep(min(wait, 60))
        wait *= 2
    raise RuntimeError(f"Dukascopy {day}: gave up after {tries} tries ({err})")


def download(start: date, end: date, *, sym: str = SYMBOL, pause_s: float = 0.4, progress=print, opener=None) -> int:
    """Fetch every missing day from start to end (Saturdays skipped: closed all day UTC). Returns days fetched."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [d for d in days if d.weekday() != 5 and not day_file(sym, d).exists()]
    if not todo:
        return 0
    progress(f"Dukascopy {sym}: {len(todo)} day(s) to fetch ({todo[0]} → {todo[-1]})")
    for n, d in enumerate(todo, 1):
        rows = fetch_day(sym, d, opener=opener)
        f = day_file(sym, d)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        with gzip.open(tmp, "wt") as fh:
            json.dump(rows, fh)
        tmp.replace(f)
        if n % 50 == 0 or n == len(todo):
            progress(f"Dukascopy {sym}: {n}/{len(todo)} days (up to {d})")
        if pause_s:
            time.sleep(pause_s)
    return len(todo)


def load_1m(start: date, end: date, sym: str = SYMBOL) -> list[list]:
    out = []
    d = start
    while d <= end:
        f = day_file(sym, d)
        if f.exists():
            with gzip.open(f, "rt") as fh:
                out += json.load(fh)
        d += timedelta(days=1)
    return out


def to_5m(rows: list[list]) -> list[Bar]:
    """1m rows -> 5m bars on the clock (:00, :05, …); a bucket with any minutes counts."""
    out: list[Bar] = []
    cur = None
    for t, o, h, l, c in rows:
        key = t - t % 300
        if cur is None or cur[0] != key:
            if cur is not None:
                out.append(Bar(datetime.fromtimestamp(cur[0], timezone.utc), *cur[1:]))
            cur = [key, o, h, l, c]
        else:
            cur[2], cur[3], cur[4] = max(cur[2], h), min(cur[3], l), c
    if cur is not None:
        out.append(Bar(datetime.fromtimestamp(cur[0], timezone.utc), *cur[1:]))
    return out


def bars_5m(start: date, end: date, *, fetch: bool = True, progress=print) -> list[Bar]:
    """5m bars for start..end (UTC days), downloading what's missing first."""
    if fetch:
        download(start, end, progress=progress)
    return to_5m(load_1m(start, end))
