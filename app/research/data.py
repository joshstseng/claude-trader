"""Data for the research lab: Alpaca daily and intraday bars for ETFs, and HistData Nasdaq-100 1m
(the same cache Brix uses). Its own cache folder (data/bars/lab/), so the bots' caches are never touched."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import paths

NY = ZoneInfo("America/New_York")
LAB = paths.SHARED_DATA_DIR / "bars" / "lab"


@dataclass
class D:                       # one bar
    t: datetime                # start (UTC for intraday; the session date at 00:00 NY for daily)
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


def _client():
    from app.marketdata import _client as c
    return c()


def daily(sym: str, start: date = date(2016, 1, 1), end: date = date(2026, 11, 19), fetch: bool = True) -> list[D]:
    """Daily bars, split- and dividend-adjusted (total return), SIP."""
    f = LAB / "1d" / f"{sym}.json.gz"
    if not f.exists():
        if not fetch:
            return []
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day,
                               start=datetime.combine(start, dtime(0), tzinfo=NY),
                               end=datetime.combine(end, dtime(23, 59), tzinfo=NY),
                               feed=DataFeed.SIP, adjustment=Adjustment.ALL)
        bars = _client().get_stock_bars(req).data.get(sym, [])
        rows = [[b.timestamp.astimezone(NY).date().isoformat(), b.open, b.high, b.low, b.close, b.volume] for b in bars]
        f.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(f, "wt") as fh:
            json.dump(rows, fh)
    with gzip.open(f, "rt") as fh:
        rows = json.load(fh)
    return [D(datetime.combine(date.fromisoformat(r[0]), dtime(0), tzinfo=NY), *r[1:6]) for r in rows]


def intraday(sym: str, year: int, minutes: int = 5, fetch: bool = True) -> list[D]:
    """Regular- and extended-hours bars for one year (split-adjusted), cached per year."""
    f = LAB / f"{minutes}m" / sym / f"{year}.json.gz"
    if not f.exists():
        if not fetch:
            return []
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        end = min(datetime(year + 1, 1, 1, tzinfo=NY), datetime.now(timezone.utc) - timedelta(minutes=20))
        req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame(minutes, TimeFrameUnit.Minute),
                               start=datetime(year, 1, 1, tzinfo=NY), end=end,
                               feed=DataFeed.SIP, adjustment=Adjustment.SPLIT)
        bars = _client().get_stock_bars(req).data.get(sym, [])
        rows = [[int(b.timestamp.timestamp()), b.open, b.high, b.low, b.close, b.volume] for b in bars]
        f.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(f, "wt") as fh:
            json.dump(rows, fh)
    with gzip.open(f, "rt") as fh:
        rows = json.load(fh)
    return [D(datetime.fromtimestamp(r[0], timezone.utc), *r[1:6]) for r in rows]


def nq_1m(start: date, end: date) -> list[D]:
    """HistData Nasdaq-100 1m (Brix's cache)."""
    from app.backtest import histdata
    return [D(datetime.fromtimestamp(r[0], timezone.utc), *r[1:5]) for r in histdata.load_1m(start, end)]
