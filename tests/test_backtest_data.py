"""Backtest data: focus lists without look-ahead, the bar cache, and failed downloads never cached."""

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import marketdata
from app.backtest import data
from app.outcomes import NY, Bar

FL = {"top_n_by_dollar_volume": 2, "min_price": 5, "include_daily_scan_hits": True,
      "max_daily_scan_hits": 1, "min_daily_volume": 1_000_000}
D = date(2026, 3, 2)   # a Monday


def days_before(n, end=D):
    out, d = [], end - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(data, "DAILY_DIR", root / "1d"),
                        mock.patch.object(data, "M5_DIR", root / "5m")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def daily(self, sym, closes, vols, extra=None):
        rows = [[d.isoformat(), c, c, c, c, v] for d, c, v in zip(days_before(len(closes)), closes, vols)]
        if extra:                                           # a bar ON day D (must be ignored)
            rows.append([D.isoformat(), *extra])
        data._write_gz(data.DAILY_DIR / f"{sym}.json.gz", {"symbol": sym, "rows": rows})


class FocusTest(Tmp):
    def test_ranked_by_last_session_dollars_and_no_look_ahead(self):
        flat = [50.0] * 40
        self.daily("BIG", flat, [3e6] * 40)                     # $150M yesterday
        self.daily("MID", flat, [2e6] * 40)                     # $100M
        self.daily("SMALL", flat, [1.5e6] * 40,                 # $75M yesterday...
                   extra=[50, 50, 50, 50, 9e9])                 # ...and a giant day D that must not count
        self.daily("CHEAP", [3.0] * 40, [9e9] * 40)             # under $5: never in
        out = data.focus_for(D, data.DailyStore(["BIG", "MID", "SMALL", "CHEAP"]), FL)
        self.assertEqual(out["top"], ["BIG", "MID"])

    def test_daily_setup_hits_are_added_and_capped(self):
        rising = [50.0] * 39 + [60.0]                           # a 20-day closing-high breakout yesterday
        self.daily("BIG", [50.0] * 40, [3e6] * 40)
        self.daily("MID", [50.0] * 40, [2e6] * 40)
        self.daily("BRK1", rising, [1.2e6] * 40)
        self.daily("BRK2", rising, [1.1e6] * 40)
        self.daily("THIN", rising, [5e5] * 40)                  # breakout but under 1M shares: no
        out = data.focus_for(D, data.DailyStore(["BIG", "MID", "BRK1", "BRK2", "THIN"]), FL)
        self.assertEqual(out["daily_hits_total"], 2)
        self.assertEqual(out["daily_hits"], ["BRK1"])           # most traded first, cap of 1
        self.assertEqual(out["symbols"], ["BIG", "MID", "BRK1"])

    def test_needs_30_days_of_closes_for_setups(self):
        self.daily("NEW", [50.0] * 25 + [60.0], [2e6] * 26)     # a recent listing
        out = data.focus_for(D, data.DailyStore(["NEW"]), FL)
        self.assertEqual(out["daily_hits_total"], 0)


class DayBarsCacheTest(Tmp):
    def test_fetched_once_then_cached(self):
        t = datetime(2026, 3, 2, 9, 30, tzinfo=NY)
        calls = []

        def fake(symbols, day):
            calls.append(list(symbols))
            return {"AAA": [Bar(t, 1, 2, 0.5, 1.5, 100)]}      # BBB: no bars that day

        with mock.patch.object(marketdata, "bars_5m", fake):
            first = data.day_bars(D, ["AAA", "BBB"])
            again = data.day_bars(D, ["AAA", "BBB"])
        self.assertEqual(calls, [["AAA", "BBB"]])               # second call: all from the cache
        self.assertEqual(first, again)
        self.assertEqual(first["AAA"][0].c, 1.5)
        self.assertNotIn("BBB", first)


class FailedDownloadsTest(Tmp):
    def test_a_bad_symbol_is_isolated_and_never_cached(self):
        def get_stock_bars(req):
            syms = req.symbol_or_symbols
            if "BAD" in syms:
                raise RuntimeError("invalid symbol")
            ts = datetime(2026, 2, 27, tzinfo=NY)
            return SimpleNamespace(data={s: [SimpleNamespace(timestamp=ts, open=1, high=1, low=1, close=1,
                                                             volume=1)] for s in syms})
        client = SimpleNamespace(get_stock_bars=get_stock_bars)
        with mock.patch.object(data, "_client", lambda: client), mock.patch.object(data.time, "sleep"):
            data.fetch_daily(["AAA", "BAD", "CCC", "DDD"], date(2026, 1, 1), date(2026, 2, 27),
                             progress=lambda m: None)
        cached = sorted(p.name for p in data.DAILY_DIR.iterdir())
        self.assertEqual(cached, ["AAA.json.gz", "CCC.json.gz", "DDD.json.gz"])   # BAD: not cached


if __name__ == "__main__":
    unittest.main()
