"""Historical bars from Alpaca (full consolidated feed, SIP).

The free plan serves SIP bars that are at least 15 minutes old, which is all we need: the
after-close step runs at 4:15 PM, and the backtest only reads the past.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from functools import lru_cache

from app import settings
from app.outcomes import NY, Bar, bars_from_alpaca

BATCH = 100   # symbols per request


@lru_cache(maxsize=1)
def _client():
    from alpaca.data.historical import StockHistoricalDataClient
    a = settings.alpaca_settings()
    return StockHistoricalDataClient(a.api_key, a.secret_key)


def bars_5m(symbols: list[str], day: date, *, start: dtime = dtime(9, 30),
            end: dtime = dtime(16, 0)) -> dict[str, list[Bar]]:
    """5-minute bars for one session day, New York time, regular hours by default."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    out: dict[str, list[Bar]] = {}
    syms = sorted({s.upper() for s in symbols})
    for i in range(0, len(syms), BATCH):
        req = StockBarsRequest(symbol_or_symbols=syms[i:i + BATCH],
                               timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                               start=datetime.combine(day, start, tzinfo=NY),
                               end=datetime.combine(day, end, tzinfo=NY), feed=DataFeed.SIP)
        data = _client().get_stock_bars(req).data
        for sym, bars in data.items():
            out[sym] = bars_from_alpaca(bars)
    return out
