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


def series(moves: dict[int, float] | None = None, chop: bool = False, end=dtime(22, 0)):
    """5m NQ bars from 6:30 AM PT (warm-up: a steady uptrend, or chop) to `end`.
    moves = {session bar k: close - open}, k = 0 is the 4:00 PM PT bar."""
    moves = moves or {}
    t = datetime.combine(D, dtime(6, 30), tzinfo=PT)
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
        bars = series(end=dtime(7, 35))           # 6:30 .. 7:30 = 13 bars -> 4 whole 15m bars
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

    def test_chop_is_filtered_by_adx(self):
        r = mrs.run_session(series(DIP, chop=True), D, S)
        self.assertEqual(r.trades, [])
        self.assertIn("ADX", r.skipped[0]["why"])

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

    def test_no_peeking_at_an_unfinished_15m_bar(self):
        """The trend reading at a 4:30 PM cross comes from the 4:15 bar (complete at 4:30), not the 4:30 one."""
        bars = series(DIP)
        r15 = mrs.rsi([b.c for b in mrs.resample(bars, 15)])
        b15 = mrs.resample(bars, 15)
        i = next(j for j, b in enumerate(b15) if b.start.astimezone(PT).strftime("%H:%M") == "16:15")
        t = mrs.run_session(bars, D, S).trades[0]
        self.assertEqual(t.rsi15, round(r15[i], 1))

    def test_sizing(self):
        self.assertEqual(mrs.contracts_for(30, S), 8)          # $500 / (30 × $2 + $2.50) = 8
        self.assertEqual(mrs.contracts_for(300, S), 0)
        self.assertEqual(mrs.session_bounds(D, S)[0].astimezone(mrs.ZoneInfo("America/New_York")).hour, 19)


if __name__ == "__main__":
    unittest.main()
