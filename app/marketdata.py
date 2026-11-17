"""Historical bars from Alpaca (full consolidated feed, SIP).

The free plan serves SIP bars that are at least 15 minutes old, which is all we need: the
after-close step runs at 4:15 PM, and the backtest only reads the past.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from functools import lru_cache

from app import settings
from app.outcomes import NY, Bar, bars_from_alpaca

BATCH = 100   # symbols per request
SIP_DELAY = timedelta(minutes=16)   # the free plan refuses SIP data from the last 15 minutes


def not_too_recent(t: datetime) -> datetime:
    """Clamp a request's end so the free plan doesn't refuse it."""
    return min(t, datetime.now(NY) - SIP_DELAY)


@lru_cache(maxsize=1)
def _client():
    from alpaca.data.historical import StockHistoricalDataClient
    settings.load_env()
    a = settings.alpaca_settings()
    return StockHistoricalDataClient(a.api_key, a.secret_key)


def bars_5m(symbols: list[str], day: date, *, start: dtime = dtime(9, 30),
            end: dtime = dtime(16, 0), feed: str = "sip") -> dict[str, list[Bar]]:
    """5-minute bars for one session day, New York time, regular hours by default.
    feed "sip" = the whole market (free plan: at least 15 minutes old); "iex" = the IEX exchange
    only, but real-time on the free plan."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    out: dict[str, list[Bar]] = {}
    syms = sorted({s.upper() for s in symbols})
    for i in range(0, len(syms), BATCH):
        req = StockBarsRequest(symbol_or_symbols=syms[i:i + BATCH],
                               timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                               start=datetime.combine(day, start, tzinfo=NY),
                               end=(not_too_recent if feed == "sip" else (lambda x: x))(
                                   datetime.combine(day, end, tzinfo=NY)),
                               feed=DataFeed.SIP if feed == "sip" else DataFeed.IEX)
        data = _client().get_stock_bars(req).data
        for sym, bars in data.items():
            out[sym] = bars_from_alpaca(bars)
    return out
