"""Mr. S: indicators and the session walk (plans/mrs-strategy.md)."""

import copy
import json
import math
import unittest
from datetime import date, datetime, time as dtime, timedelta

from app import paths
from app.strategies import mrs

S = json.loads((paths.STRATEGY_CONFIG_DIR / "mrs.json").read_text())
D = date(2026, 11, 17)
PT = mrs.PT


def series(moves: dict[int, float] | None = None, chop: bool = False, end=dtime(22, 0), start=dtime(0, 30)):
    """5m NQ bars from 12:30 AM PT (enough for a 1h RSI) (warm-up: a steady uptrend, or chop) to `end`.
    moves = {session bar k: close - open}, k = 0 is the 4:00 PM PT bar."""
    moves = moves or {}
    t = datetime.combine(D, start, tzinfo=PT)
    stop_at = datetime.combine(D, end, tzinfo=PT)
    s_start = datetime.combine(D, dtime(16, 0), tzinfo=PT)
    bars, c, i = [], 20000.0, 0
    while t < stop_at:
        o = c
        k = int((t - s_start) / mrs.FIVE) if t >= s_start else None
        if k is not None and k in moves:
            c = o + moves[k]
        elif chop:
            c = o + (1.5 if i % 2 else -1.5)
        else:
            c = o + (1.5 if i % 2 else 0.0)
        bars.append(mrs.Bar(t, o, max(o, c) + 0.5, min(o, c) - 0.5, c))
        t += mrs.FIVE
        i += 1
    return bars


def mirror(bars, around=40000.0):
    return [mrs.Bar(b.start, around - b.o, around - b.l, around - b.h, around - b.c) for b in bars]


DIP = {6: -30.0, 7: 5.0}           # 4:30 PM closes below the lower band; 4:35 still outside, 4:40 back inside


class IndicatorTest(unittest.TestCase):
    def test_bollinger(self):
        closes = [float(x) for x in range(1, 21)]
        lo, mid, up = mrs.bollinger(closes, 20, 2)[-1]
        sd = math.sqrt(sum((x - 10.5) ** 2 for x in closes) / 20)
        self.assertAlmostEqual(mid, 10.5)
        self.assertAlmostEqual(up - mid, 2 * sd)
        self.assertAlmostEqual(mid - lo, 2 * sd)
        self.assertIsNone(mrs.bollinger(closes, 20, 2)[18])

    def test_rsi(self):
        self.assertEqual(mrs.rsi([float(x) for x in range(30)])[-1], 100.0)
        down = mrs.rsi([float(-x) for x in range(30)])
        self.assertEqual(down[-1], 0.0)
        self.assertIsNone(down[13])
        zig = mrs.rsi([100.0 + (1 if i % 2 else 0) for i in range(60)])
        self.assertAlmostEqual(zig[-1], 50.0, delta=3)

    def test_adx_trend_vs_chop(self):
        trend = series(end=dtime(15, 0))
        chop = series(chop=True, end=dtime(15, 0))
        a_trend = mrs.adx(mrs.resample(trend, 15))[-1]
        a_chop = mrs.adx(mrs.resample(chop, 15))[-1]
        self.assertGreater(a_trend, 50)
        self.assertLess(a_chop, 20)
        self.assertIsNone(mrs.adx(mrs.resample(trend, 15))[26])
        self.assertIsNotNone(mrs.adx(mrs.resample(trend, 15))[27])

    def test_resample_keeps_only_whole_buckets(self):
        bars = series(end=dtime(7, 35), start=dtime(6, 30))   # 6:30 .. 7:30 = 13 bars -> 4 whole 15m bars
        out = mrs.resample(bars, 15)
        self.assertEqual([b.start.strftime("%H:%M") for b in out], ["06:30", "06:45", "07:00", "07:15"])
        self.assertEqual(out[0].o, bars[0].o)
        self.assertEqual(out[0].c, bars[2].c)
        self.assertEqual(out[0].h, max(b.h for b in bars[:3]))


class SessionTest(unittest.TestCase):
    def test_a_long_hits_2r(self):
        bars = series({**DIP, 9: 20.0})                               # a rally right after the entry
        r = mrs.run_session(bars, D, S)
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        self.assertEqual((t.side, t.cross_at[11:16], t.entry_at[11:16]), ("long", "16:30", "16:40"))
        cross_low = min(b.l for b in bars if b.start.astimezone(PT).strftime("%H:%M") in ("16:30", "16:40"))
        self.assertEqual(t.stop, cross_low - 0.5)                     # the lowest low, 2 ticks below
        self.assertEqual(t.target_2r, t.entry + 2 * (t.entry - t.stop))
        self.assertEqual(t.contracts, 20)                             # 1% wants more, capped at 20
        self.assertEqual((t.result, t.exit), ("2R", t.target_2r))
        risk = t.entry - t.stop
        self.assertEqual(t.pnl_usd, 2 * risk * 2 * 20 - 20 * (2 * 0.75 + 0.25 * 2))   # 1 tick slippage (entry)
        self.assertAlmostEqual(t.r, t.pnl_usd / (risk * 2 * 20), places=3)

    def test_the_middle_band_when_its_nearer(self):
        r = mrs.run_session(series(DIP), D, S)
        t = r.trades[0]
        self.assertEqual(t.result, "middle")
        self.assertLess(t.exit, t.target_2r)
        no_mid = copy.deepcopy(S)
        no_mid["exit"]["middle_band"] = False
        self.assertNotEqual(mrs.run_session(series(DIP), D, no_mid).trades[0].result, "middle")

    def test_a_short_is_the_mirror_of_a_long(self):
        long = mrs.run_session(series(DIP), D, S).trades[0]
        short = mrs.run_session(mirror(series(DIP)), D, S).trades[0]
        self.assertEqual(short.side, "short")
        self.assertEqual((short.result, short.r, short.contracts), (long.result, long.r, long.contracts))
        self.assertEqual(short.stop, 40000 - long.stop)

    def test_a_stop(self):
        r = mrs.run_session(series({**DIP, 9: -30.0}), D, S)
        t = r.trades[0]
        self.assertEqual((t.result, t.exit), ("stop", t.stop))
        self.assertLess(t.r, -1.0)                                    # 1R plus costs
        self.assertGreater(t.r, -1.3)

    def test_break_even_then_lock_in_1r(self):
        trail = copy.deepcopy(S)
        trail["exit"].update(middle_band=False, breakeven_at_r=1.0, lock_r=1.0)
        # risk is 6 points; entry at the 4:40 bar's close
        be = mrs.run_session(series({**DIP, 9: 7.0, 10: -10.0}), D, trail).trades[0]   # +1.25R, then back
        self.assertEqual((be.result, be.exit, be.stop_now), ("be_stop", be.entry, be.entry))
        self.assertLess(be.r, 0)                                                        # just the costs
        self.assertGreater(be.r, -0.25)                                                 # (6-pt stop: costs ~0.21R)
        lock = mrs.run_session(series({**DIP, 9: 9.0, 10: -2.0, 11: -3.0}), D, trail).trades[0]
        self.assertEqual((lock.result, lock.exit), ("lock_stop", lock.entry + 6.0))      # high at 1.58R held
        self.assertGreater(lock.r, 0.75)                                                # +1R less ~0.21R costs
        off = mrs.run_session(series({**DIP, 9: 7.0, 10: -10.0}), D, dict(S, exit=dict(S["exit"], middle_band=False)))
        self.assertIsNone(off.trades[0].stop_now)                                       # baseline: never moves

    def test_chop_is_filtered_by_adx(self):
        r = mrs.run_session(series(DIP, chop=True), D, S)
        self.assertEqual(r.trades, [])
        self.assertIn("ADX", r.skipped[0]["why"])

    def test_version_b_fades_ranges_only(self):
        b = copy.deepcopy(S)
        b["filters"].update(adx_min=-1, adx_max=20, use_rsi=False, rsi_long_above=101)   # RSI ignored
        chop = mrs.run_session(series({6: -20.0, 7: 8.0}, chop=True), D, b)
        self.assertEqual(len(chop.trades), 1)                        # a range: faded
        self.assertEqual(chop.trades[0].side, "long")
        trend = mrs.run_session(series({6: -20.0, 7: 8.0}), D, b)   # a strong trend: skipped
        self.assertEqual(trend.trades, [])
        self.assertIn("(trending)", trend.skipped[0]["why"])

    def test_rsi_must_agree(self):
        strict = copy.deepcopy(S)
        strict["filters"]["rsi_long_above"] = 101
        r = mrs.run_session(series(DIP), D, strict)
        self.assertEqual(r.trades, [])
        self.assertIn("RSI", r.skipped[0]["why"])

    def test_two_bars_to_come_back_inside(self):
        first = mrs.run_session(series({6: -30.0, 7: 8.0}), D, S)              # back on the next bar
        self.assertEqual(first.trades[0].entry_at[11:16], "16:35")
        second = mrs.run_session(series(DIP), D, S)                           # on the bar after: still ok
        self.assertEqual(second.trades[0].entry_at[11:16], "16:40")
        never = mrs.run_session(series({6: -40.0, 7: 5.0}), D, S)
        self.assertIn("didn't come back inside in time", [x["why"] for x in never.skipped])

    def test_tight_stop_and_late_entries_are_skipped(self):
        tight = copy.deepcopy(S)
        tight["entry"]["min_stop_points"] = 20
        self.assertIn("stop too tight", mrs.run_session(series(DIP), D, tight).skipped[0]["why"])
        late = mrs.run_session(series({66: -30.0, 67: 5.0}), D, S)            # entry bar closes 9:45 PM: ok
        self.assertEqual(late.trades[0].entry_at[11:16], "21:40")
        self.assertEqual(late.trades[0].result, "session_end")
        self.assertEqual(late.trades[0].exit_at[11:16], "21:55")
        later = mrs.run_session(series({67: -30.0, 68: 5.0}), D, S)
        self.assertEqual(later.trades, [])
        self.assertIn("too late in the session", later.skipped[0]["why"])

    def test_two_losses_end_the_session(self):
        any_rsi = copy.deepcopy(S)                             # (the losses drag RSI down: test the limit alone)
        any_rsi["filters"]["rsi_long_above"] = 0
        moves = {6: -30.0, 7: 5.0, 9: -30.0,                   # loss 1
                 30: -30.0, 31: 5.0, 33: -30.0,                # loss 2
                 54: -30.0, 55: 5.0}                           # third setup: skipped
        r = mrs.run_session(series(moves), D, any_rsi)
        self.assertEqual([t.result for t in r.trades], ["stop", "stop"])
        self.assertTrue(r.stopped_for_loss)
        self.assertIn("session loss limit", r.skipped[-1]["why"])

    def test_a_3r_session_stops_trading(self):
        any_rsi = copy.deepcopy(S)
        any_rsi["filters"]["rsi_long_above"] = 0
        win = {9: 20.0}                                         # a rally to 2R right after each entry
        moves = {6: -30.0, 7: 5.0, **win,
                 30: -30.0, 31: 5.0, 33: 20.0,
                 54: -30.0, 55: 5.0}                            # third setup: skipped after ~3.8R
        r = mrs.run_session(series(moves), D, any_rsi)
        self.assertEqual([t.result for t in r.trades], ["2R", "2R"])              # +3.7R after costs
        self.assertTrue(r.stopped_for_win)
        self.assertIn("session win limit", r.skipped[-1]["why"])
        no_cap = copy.deepcopy(any_rsi)
        no_cap["account"]["max_session_win_r"] = None
        self.assertFalse(mrs.run_session(series(moves), D, no_cap).stopped_for_win)

    def test_no_peeking_at_an_unfinished_bar(self):
        """At a 4:30 PM cross: RSI from the 3:00 PM 1h bar (complete at 4:00, the 4:00 one isn't done),
        ADX from the 4:15 15m bar (complete at 4:30)."""
        bars = series({**DIP, 0: 3.0, 1: -2.0, 2: 3.0, 3: -1.0})       # make the 4:00 hour differ from 3:00
        h1 = mrs.resample(bars, 60)
        r1 = mrs.rsi([b.c for b in h1])
        i = next(j for j, b in enumerate(h1) if b.start.astimezone(PT).strftime("%H:%M") == "15:00")
        m15 = mrs.resample(bars, 15)
        a15 = mrs.adx(m15)
        k = next(j for j, b in enumerate(m15) if b.start.astimezone(PT).strftime("%H:%M") == "16:15")
        t = mrs.run_session(bars, D, S).trades[0]
        self.assertEqual(t.rsi, round(r1[i], 1))
        self.assertEqual(t.adx, round(a15[k], 1))

    def test_sizing(self):
        self.assertEqual(mrs.contracts_for(30, S), 8)          # $500 / (30 × $2 + $2.50) = 8
        self.assertEqual(mrs.contracts_for(300, S), 0)
        self.assertEqual(mrs.session_bounds(D, S)[0].astimezone(mrs.ZoneInfo("America/New_York")).hour, 19)


class BacktestTest(unittest.TestCase):
    def test_a_run_is_saved_and_summarised(self):
        import tempfile
        from pathlib import Path
        from app.backtest import mrs as bt
        bars = series({**DIP, 9: 20.0})
        with tempfile.TemporaryDirectory() as d:
            res = bt.run(D, D, label="baseline", db_path=Path(d) / "b.db", reports=Path(d) / "r", bars=bars)
            self.assertEqual((res.headline["sessions"], res.headline["trades"]), (1, 1))
            self.assertEqual(res.headline["results"], {"2R": 1})
            doc = json.loads((Path(d) / "r" / f"run-{res.run_id}.json").read_text())
            self.assertEqual(doc["settings"]["strategy"]["id"], "mrs")
            text = bt.summary(doc)
            self.assertIn("Mr. S · Backtest", text)
            self.assertIn("1 trades", text)
            self.assertIn("too few to judge", text)
            res2 = bt.run(D, D, label="ADX 101", overrides=["filters.adx_min=101"], db_path=Path(d) / "b.db",
                          reports=Path(d) / "r", bars=bars)
            self.assertEqual(res2.headline["trades"], 0)
            self.assertEqual(res2.run_id, res.run_id + 1)
            with self.assertRaises(ValueError):
                bt.run(D, D, label="x", overrides=["filters.nope=1"], db_path=Path(d) / "b.db",
                       reports=Path(d) / "r", bars=bars)

    def test_yahoo_bars_drop_the_unfinished_one(self):
        from datetime import timezone
        from app.backtest import mrs as bt
        t0 = int(datetime(2026, 11, 20, 17, 0, tzinfo=timezone.utc).timestamp())
        doc = {"chart": {"result": [{"timestamp": [t0, t0 + 300, t0 + 361],
                                     "indicators": {"quote": [{"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
                                                               "close": [1, 2, 3], "volume": [0, 0, 0]}]}}]}}
        now = datetime.fromtimestamp(t0 + 400, timezone.utc)
        self.assertEqual([b.c for b in bt.parse_yahoo(doc, now)], [1.0])       # t0+300 still forming; odd tick
        old = [mrs.Bar(datetime.fromtimestamp(t0, timezone.utc), 0, 0, 0, 0)]
        merged = bt.merge(old, bt.parse_yahoo(doc, now))
        self.assertEqual([b.c for b in merged], [1.0])


def series1(moves: dict[int, float] | None = None, inside: dict[int, list[float]] | None = None):
    """1m bars (and the 5m bars built from them) on the same pattern as series(): each 5m move is split
    into 5 equal 1m moves, unless `inside` gives that 5m bar's five 1m moves."""
    from app.backtest.dukascopy import to_5m
    moves, inside = moves or {}, inside or {}
    t = datetime.combine(D, dtime(0, 30), tzinfo=PT)
    stop_at = datetime.combine(D, dtime(22, 0), tzinfo=PT)
    s_start = datetime.combine(D, dtime(16, 0), tzinfo=PT)
    one, c, i = [], 20000.0, 0
    while t < stop_at:
        k = int((t - s_start) / mrs.FIVE) if t >= s_start else None
        step = inside.get(k) or [(moves[k] if k in moves else (1.5 if i % 2 else 0.0)) / 5] * 5
        for n, dm in enumerate(step):
            o = c
            c = o + dm
            one.append(mrs.Bar(t + n * mrs.ONE, o, max(o, c) + 0.1, min(o, c) - 0.1, c))
        t += mrs.FIVE
        i += 1
    rows = [[int(b.start.timestamp()), b.o, b.h, b.l, b.c] for b in one]
    return one, to_5m(rows)


class OneMinuteEntryTest(unittest.TestCase):
    def setUp(self):
        self.s = copy.deepcopy(S)
        self.s["entry"]["timeframe"] = "1m"
        self.s["entry"]["min_stop_points"] = 2

    def test_enters_on_the_first_bullish_minute_back_inside(self):
        one, five = series1({6: -30.0, 7: 10.0})
        r = mrs.run_session(five, D, self.s, bars1=one)
        t = r.trades[0]
        when = datetime.fromisoformat(t.entry_at)
        self.assertEqual(t.cross_at[11:16], "16:30")
        self.assertTrue(datetime.fromisoformat(t.cross_at) + mrs.FIVE <= when < datetime.fromisoformat(t.cross_at) + 3 * mrs.FIVE)
        m = next(b for b in one if b.start == when)
        self.assertGreater(m.c, m.o)                                         # a bullish candle
        self.assertEqual(t.entry, round(m.c, 2))
        low = min(b.l for b in one if datetime.fromisoformat(t.cross_at) <= b.start <= when)
        self.assertEqual(t.stop, mrs._round_tick(low - 0.5, 0.25, True))   # the swing low, 2 ticks below
        with self.assertRaises(ValueError):
            mrs.run_session(five, D, self.s)                                 # 1m needs 1m bars

    def test_no_bullish_minute_in_10_minutes_drops_it(self):
        one, five = series1({6: -30.0, 7: -1.0, 8: -1.0, 9: -1.0})
        r = mrs.run_session(five, D, self.s, bars1=one)
        self.assertNotIn("16:3", "".join(t.entry_at for t in r.trades))
        self.assertIn("didn't come back inside in time", [x["why"] for x in r.skipped])

    def test_one_minute_bars_settle_a_bar_that_hits_both(self):
        """A 5m bar reaches 2R and then the stop: 5m bars can't tell, so the 5m walk counts the stop;
        the 1m walk sees 2R first."""
        one, five = series1({6: -30.0, 7: 10.0})
        t0 = mrs.run_session(five, D, self.s, bars1=one).trades[0]
        risk = t0.entry - t0.stop
        k = int((datetime.fromisoformat(t0.entry_at) + mrs.ONE - datetime.combine(D, dtime(16, 0), tzinfo=PT))
                / mrs.FIVE) + 1                                              # the next whole 5m bar
        up, down = 2.2 * risk, -4.5 * risk
        one, five = series1({6: -30.0, 7: 10.0}, inside={k: [up, down, 0.0, 0.0, 0.0]})
        t1 = mrs.run_session(five, D, self.s, bars1=one).trades[0]
        self.assertIn(t1.result, ("2R", "middle"))                          # a target first, not the stop
        self.assertGreater(t1.r, 0)
        bar = next(b for b in five if b.start == datetime.combine(D, dtime(16, 0), tzinfo=PT) + k * mrs.FIVE)
        self.assertTrue(bar.h >= t1.target_2r and bar.l <= t1.stop)          # the 5m bar touched both


class DukascopyTest(unittest.TestCase):
    @staticmethod
    def bi5(rows):
        import lzma
        import struct
        raw = b"".join(struct.pack(">5if", *r) for r in rows)
        return lzma.compress(raw, format=lzma.FORMAT_ALONE)

    def test_parse_and_5m_bars(self):
        from app.backtest import dukascopy as dk
        day = date(2025, 6, 10)
        raw = self.bi5([(0, 21805719, 21799965, 21795487, 21806475, 0.01),     # open, close, low, high
                        (60, 21800000, 21810000, 21799000, 21812000, 0.01),
                        (120, 1, 1, 1, 1, 0.0),                                 # flat, no volume: dropped
                        (300, 21810000, 21805000, 21804000, 21811000, 0.01)])
        rows = dk.parse(raw, day)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][1:], [21805.719, 21806.475, 21795.487, 21799.965])   # o, h, l, c
        bars = dk.to_5m(rows)
        self.assertEqual(len(bars), 2)
        self.assertEqual((bars[0].o, bars[0].h, bars[0].l, bars[0].c), (21805.719, 21812.0, 21795.487, 21810.0))
        self.assertEqual(bars[1].start.strftime("%H:%M"), "00:05")

    def test_download_retries_caches_and_resumes(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from urllib.error import HTTPError
        from app.backtest import dukascopy as dk
        calls = []

        def opener(url):
            calls.append(url)
            if len(calls) == 1:
                raise HTTPError(url, 503, "busy", None, None)
            return self.bi5([(0, 1000, 2000, 500, 2500, 1.0)])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(dk, "CACHE", Path(d)), \
                mock.patch.object(dk.time, "sleep"):
            n = dk.download(date(2025, 6, 6), date(2025, 6, 8), pause_s=0, progress=lambda m: None, opener=opener)
            self.assertEqual(n, 2)                                   # Fri + Sun; Saturday skipped
            self.assertIn("/2025/05/06/", calls[0])                  # the month is 0-based in the URL
            self.assertEqual(len(calls), 3)                          # one 503, retried
            self.assertEqual(dk.download(date(2025, 6, 6), date(2025, 6, 8), pause_s=0, opener=opener), 0)
            self.assertEqual(len(dk.load_1m(date(2025, 6, 6), date(2025, 6, 8))), 2)


class HistDataTest(unittest.TestCase):
    def test_file_time_follows_european_daylight_saving(self):
        from app.backtest import histdata as hd
        utc = lambda x: datetime.fromtimestamp(hd.to_utc(x), mrs.ZoneInfo("UTC")).strftime("%m-%d %H:%M")
        self.assertEqual(utc("20250115 180000"), "01-15 23:00")      # winter: UTC−5 (6 PM New York)
        self.assertEqual(utc("20250715 180000"), "07-15 22:00")      # summer: UTC−4 (6 PM New York)
        self.assertEqual(utc("20251028 170000"), "10-28 22:00")      # Europe already off DST, US not yet

    def test_periods_and_fetch(self):
        from app.backtest import histdata as hd
        self.assertEqual(hd.periods(date(2024, 5, 1), date(2026, 3, 9), today=date(2026, 3, 10)),
                         ["2024", "2025", "2026/01", "2026/02"])
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("DAT_ASCII_NSXUSD_M1_2023.csv", "20230102 180000;1.5;2;1;1.75;0\n20230102 180100;1.75;2;1.5;2;0\n")
        posted = []

        def http(url, data=None, referer=None):
            if data is None:
                return b'<input type="hidden" name="tk" id="tk" value="abc">'
            posted.append(data)
            return buf.getvalue()
        rows = hd.fetch_period("2023", http=http)
        self.assertEqual(posted[0]["tk"], "abc")
        self.assertEqual(posted[0]["datemonth"], "2023")
        self.assertEqual(rows[0][1:], [1.5, 2.0, 1.0, 1.75])
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
