"""Historical data for the backtest, from Alpaca (full consolidated feed, SIP), cached on disk.

    data/bars/calendar.json          market days with their open/close (incl. early closes)
    data/bars/1d/<SYM>.json.gz       daily bars, split-adjusted (for the focus list and daily setups)
    data/bars/5m/<YYYY-MM-DD>.json.gz  that day's 5-minute bars for its focus list (raw prices)
    data/bars/focus/<YYYY-MM-DD>.json  that day's focus list

No look-ahead: the focus list for day D only uses daily bars from before D, ranked the same way
as the live bot (last session's price x volume), plus the skill's own daily setups on the same
~3 months of closes the live scan reads.

Blind spot: the stock list is today's, so stocks delisted since are missing.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable, Iterable

from app import market, paths
from app.market import Session
from app.outcomes import NY, Bar

log = logging.getLogger(__name__)
CACHE = paths.SHARED_DATA_DIR / "bars"
DAILY_DIR, M5_DIR, FOCUS_DIR = CACHE / "1d", CACHE / "5m", CACHE / "focus"
CAL_FILE = CACHE / "calendar.json"
DAILY_BATCH, M5_BATCH = 200, 100
LOOKBACK_DAYS = 92          # the live daily scan reads Yahoo's "3mo" of closes
MIN_DAILY_BARS = 30         # same as the skill's scanner


def _client():
    from app.marketdata import _client as c
    return c()


def _retry(fn, what: str, tries: int = 5):
    from app.settings import SettingsError
    for i in range(tries):
        try:
            return fn()
        except SettingsError:
            raise                       # a missing key won't fix itself
        except Exception as e:  # noqa: BLE001 - rate limits and network blips
            if i == tries - 1:
                raise
            wait = 5 * (i + 1)
            log.warning("%s failed (%s); retrying in %ss", what, str(e)[:120], wait)
            time.sleep(wait)


def _write_gz(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    tmp.replace(path)


def _read_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# -------------------------------------------------------------------- calendar

def calendar(start: date, end: date) -> list[Session]:
    """Market days between start and end (inclusive), from Alpaca, cached."""
    cached = json.loads(CAL_FILE.read_text()) if CAL_FILE.exists() else {"from": "9999", "through": "", "days": {}}
    if cached["from"] > start.isoformat() or cached["through"] < end.isoformat():
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetCalendarRequest
        from app import settings
        a = settings.alpaca_settings()
        tc = TradingClient(a.api_key, a.secret_key, paper=True)
        days = _retry(lambda: tc.get_calendar(GetCalendarRequest(start=start, end=end)), "calendar")
        cached["days"].update({d.date.isoformat(): [d.open.strftime("%H:%M"), d.close.strftime("%H:%M")]
                               for d in days})
        cached["from"] = min(cached["from"], start.isoformat())
        cached["through"] = max(cached["through"], end.isoformat())
        CAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        CAL_FILE.write_text(json.dumps(cached, indent=0))
    out = []
    for k, (o, c) in sorted(cached["days"].items()):
        d = date.fromisoformat(k)
        if start <= d <= end:
            out.append(Session(d, dtime.fromisoformat(o), dtime.fromisoformat(c)))
    return out


# ----------------------------------------------------------------- daily bars

def fetch_daily(symbols: list[str], start: date, end: date, progress: Callable[[str], None] = log.info) -> None:
    """Daily bars for every symbol, cached one file per symbol. Symbols already cached through
    `end` are skipped, so a rerun only fetches what's missing."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from app.marketdata import not_too_recent

    todo = []
    for s in symbols:
        f = DAILY_DIR / f"{s}.json.gz"
        doc = _read_gz(f) if f.exists() else {}
        if doc.get("through", "") < end.isoformat() or doc.get("from", "9") > start.isoformat():
            todo.append(s)
    progress(f"daily bars: {len(symbols) - len(todo)} cached, {len(todo)} to fetch")
    for i in range(0, len(todo), DAILY_BATCH):
        batch = todo[i:i + DAILY_BATCH]
        req = StockBarsRequest(symbol_or_symbols=batch, timeframe=TimeFrame.Day,
                               start=datetime.combine(start, dtime(0), tzinfo=NY),
                               end=not_too_recent(datetime.combine(end, dtime(23, 59), tzinfo=NY)),
                               feed=DataFeed.SIP, adjustment=Adjustment.SPLIT)
        failed: set[str] = set()

        def get(syms: list[str]) -> dict:
            """One request; if Alpaca rejects it (e.g. one odd symbol), split it in half and retry,
            so a single bad symbol costs a few requests, not one per stock."""
            r = StockBarsRequest(symbol_or_symbols=syms, timeframe=TimeFrame.Day, start=req.start,
                                 end=req.end, feed=DataFeed.SIP, adjustment=Adjustment.SPLIT)
            try:
                return _retry(lambda: _client().get_stock_bars(r).data, f"daily bars ({len(syms)})", tries=2)
            except Exception as e:  # noqa: BLE001
                if len(syms) == 1:
                    log.warning("no daily bars for %s: %s", syms[0], str(e)[:100])
                    failed.add(syms[0])
                    return {}
                mid = len(syms) // 2
                return {**get(syms[:mid]), **get(syms[mid:])}

        data = get(batch)
        for s in batch:
            if s in failed:
                continue            # never cache a failed download: try again next time
            rows = [[b.timestamp.astimezone(NY).date().isoformat(), b.open, b.high, b.low, b.close, b.volume]
                    for b in data.get(s, [])]
            _write_gz(DAILY_DIR / f"{s}.json.gz", {"symbol": s, "from": start.isoformat(),
                                                  "through": end.isoformat(), "rows": rows})
        progress(f"daily bars: {min(i + DAILY_BATCH, len(todo))}/{len(todo)}")


@dataclass
class Daily:
    dates: list[str]
    closes: list[float]
    volumes: list[float]


class DailyStore:
    """All cached daily bars in memory, for building focus lists quickly."""

    def __init__(self, symbols: Iterable[str]):
        self.by_sym: dict[str, Daily] = {}
        for s in symbols:
            f = DAILY_DIR / f"{s}.json.gz"
            if f.exists():
                rows = _read_gz(f)["rows"]
                if rows:
                    self.by_sym[s] = Daily([r[0] for r in rows], [r[4] for r in rows], [r[5] for r in rows])

    def before(self, sym: str, day: date, since: date) -> tuple[list[float], float | None]:
        """(closes from `since` up to the day before `day`, last session's volume)."""
        d = self.by_sym.get(sym)
        if not d:
            return [], None
        import bisect
        hi = bisect.bisect_left(d.dates, day.isoformat())
        lo = bisect.bisect_left(d.dates, since.isoformat())
        if hi == 0:
            return [], None
        return d.closes[lo:hi], d.volumes[hi - 1]


def focus_for(day: date, store: DailyStore, fl: dict) -> dict:
    """The focus list the live bot would have built on the morning of `day` (no look-ahead)."""
    scan = market.scan_module()
    since = day - timedelta(days=LOOKBACK_DAYS)
    meta, hits = {}, []
    for sym in store.by_sym:
        closes, vol = store.before(sym, day, since)
        if not closes or vol is None:
            continue
        price = closes[-1]
        meta[sym] = {"meta": {"regularMarketPrice": price, "regularMarketVolume": vol}}
        if price < fl["min_price"] or vol < fl.get("min_daily_volume", 1_000_000) or len(closes) < MIN_DAILY_BARS:
            continue
        tags, nums = scan.find_setups(closes)
        if tags:
            hits.append({"symbol": sym, "setups": tags, "price": round(price, 2), "volume": int(vol)})
    hits.sort(key=lambda h: (-(h["price"] * h["volume"]), h["symbol"]))   # most dollars traded first, like live
    out = market.pick_focus(meta, sorted(meta), hits, fl)
    out["daily_hits_total"] = len(hits)
    return out


# ------------------------------------------------------------- 5-minute bars

def day_bars(day: date, symbols: list[str], *, fetch: bool = True, feed: str = "sip") -> dict[str, list[Bar]]:
    """The day's 5-minute bars (9:30 to the close) for `symbols`, raw prices, cached per day.
    feed "sip" (whole market, the backtest's default) or "iex" (the free real-time feed), cached apart."""
    from app.outcomes import bars_from_rows
    f = (M5_DIR if feed == "sip" else CACHE / f"5m-{feed}") / f"{day.isoformat()}.json.gz"
    doc = _read_gz(f) if f.exists() else {"day": day.isoformat(), "bars": {}, "empty": []}
    missing = [s for s in symbols if s not in doc["bars"] and s not in doc["empty"]]
    if missing and fetch:
        from app.marketdata import bars_5m
        got = _retry(lambda: bars_5m(missing, day, feed=feed), f"5m bars {day} ({feed})")
        for s in missing:
            if got.get(s):
                doc["bars"][s] = [[b.start.strftime("%H:%M"), b.o, b.h, b.l, b.c, b.v] for b in got[s]]
            else:
                doc["empty"].append(s)
        _write_gz(f, doc)
    d = day.isoformat()
    return {s: bars_from_rows([{"t": f"{d} {r[0]}", "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
                               for r in rows])
            for s, rows in doc["bars"].items() if s in symbols}


# ---------------------------------------------------------------- everything

def prepare(start: date, end: date, fl: dict, progress: Callable[[str], None] = print) -> dict:
    """Download (or reuse) everything a backtest from `start` to `end` needs."""
    t0 = time.time()
    sessions = calendar(start, end)
    progress(f"{len(sessions)} market days from {start} to {end}")
    universe = market.ensure_universe()
    fetch_daily(universe, start - timedelta(days=LOOKBACK_DAYS + 10), end, progress)
    store = DailyStore(universe)
    progress(f"daily bars in memory for {len(store.by_sym)} of {len(universe)} stocks")
    FOCUS_DIR.mkdir(parents=True, exist_ok=True)
    total_syms = 0
    for k, s in enumerate(sessions, 1):
        ff = FOCUS_DIR / f"{s.day.isoformat()}.json"
        focus = json.loads(ff.read_text()) if ff.exists() else focus_for(s.day, store, fl)
        if not ff.exists():
            ff.write_text(json.dumps(focus))
        day_bars(s.day, focus["symbols"])
        total_syms += len(focus["symbols"])
        if k % 20 == 0 or k == len(sessions):
            progress(f"5-min bars: {k}/{len(sessions)} days ({s.day}), {time.time() - t0:.0f}s so far")
    return {"days": len(sessions), "universe": len(universe), "with_daily": len(store.by_sym),
            "avg_focus": round(total_syms / max(1, len(sessions)), 1), "seconds": round(time.time() - t0)}
