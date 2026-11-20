"""Mr. S "8 AM retest" (app/strategies/mrs8.py): structure, the stop/target choice and one full day."""

import copy
import json
import unittest
from datetime import date, datetime, time as dtime, timedelta

from app import paths
from app.strategies import mrs8
from app.strategies.mrs import Bar

S = json.loads((paths.STRATEGY_CONFIG_DIR / "mrs8.json").read_text())
PT = mrs8.PT
D = date(2026, 11, 18)
T0 = datetime(2026, 11, 18, 0, 0, tzinfo=PT)


def b(i, o, h, l, c, span=mrs8.FIVE):
    return Bar(T0 + i * span, o, h, l, c)


class StructureTest(unittest.TestCase):
    def test_swings(self):
        bars = [b(0, 10, 11, 9, 10), b(1, 10, 12, 9, 11), b(2, 11, 15, 10, 14), b(3, 14, 13, 8, 9),
                b(4, 9, 12, 7, 8), b(5, 8, 11, 9, 10), b(6, 10, 11, 9, 10)]
        highs, lows = mrs8.swings(bars, mrs8.FIVE)
        self.assertEqual([(h[0], h[3]) for h in highs], [(15, 2)])
        self.assertEqual([(lo[0], lo[3]) for lo in lows], [(7, 4)])
        self.assertEqual(highs[0][2], bars[4].start + mrs8.FIVE)          # confirmed 2 bars later

    def test_fvg_and_order_block(self):
        bars = [b(0, 10, 11, 9, 10), b(1, 10, 10.5, 8, 8.5),                # a down candle
                b(2, 8.5, 14, 8.4, 13.5), b(3, 13.5, 16, 12, 15)]           # closes above its high; a gap
        g = mrs8.fvgs(bars, mrs8.FIVE)
        self.assertEqual([(x["kind"], x["lo"], x["hi"]) for x in g], [("bull", 10.5, 12)])
        ob = mrs8.order_blocks(bars, mrs8.FIVE)
        self.assertEqual([(x["kind"], x["lo"], x["hi"]) for x in ob][0], ("bull", 8, 10.5))


def day_bars(extra_5m: dict[str, tuple[float, float]], base=20000.0):
    """1m bars from 2 days before to 9:00 AM PT: a quiet zigzag, plus 5m blocks given as
    {"HH:MM": (low, close)} on day D, each block moving linearly from the previous close."""
    out, c = [], base
    t = T0 - timedelta(days=2)
    end = datetime.combine(D, dtime(9, 0), tzinfo=PT)
    k = 0
    while t < end:
        key = t.strftime("%H:%M") if t.date() == D else None
        if key in extra_5m:
            low, close = extra_5m[key]
            pts = [c + (low - c) * (i + 1) / 3 for i in range(3)] + [low + (close - low) * (i + 1) / 2 for i in range(2)]
        else:
            pts = [c + (0.5 if (k // 5) % 2 == 0 else -0.5)] * 5
        for i, p in enumerate(pts):
            o = c
            out.append(Bar(t + i * mrs8.ONE, o, max(o, p) + 0.25, min(o, p) - 0.25, p))
            c = p
        t += mrs8.FIVE
        k += 5
    return out


class DayTest(unittest.TestCase):
    def setUp(self):
        self.s = copy.deepcopy(S)
        self.s["stop"]["max_stop_atr"] = 100                                  # the synthetic ATR is tiny
        # the machinery under the first rules (runs #27–#30); the 1h stop/target have their own tests
        self.s.update(trend_filter="none")
        self.s["window"]["breakouts_from"] = "06:00"
        self.s["stop"]["swing_tf"] = "15m"
        self.s["target"].update(mode="5m", level_max_r=3.0)

    def test_a_long_retest_to_2r(self):
        bars = day_bars({
            "04:00": (19970, 19972), "04:05": (19971, 19990), "04:10": (19989, 19998),   # a 15m swing low
            "05:00": (19995, 19996), "05:05": (19995, 20004), "05:10": (19999, 20005),   # the 8:00 ET candle
            "06:00": (20004, 20015),                                                     # the breakout
            "06:05": (20012, 20012), "06:10": (19999, 20003),                            # back to the midpoint
            "06:15": (20002, 20030), "06:20": (20029, 20060), "06:25": (20059, 20080),   # away we go
        })
        d = mrs8.run_day(bars, D, self.s)
        t = d.trade
        self.assertIsNotNone(t, d.why)
        self.assertEqual((t.side, t.break_at[11:16]), ("long", "06:00"))
        ref_mid = (t.ref_hi + t.ref_lo) / 2
        self.assertEqual(t.entry, mrs8._tick(ref_mid, 0.25, True))
        self.assertEqual(t.stop_from, "15m swing low")
        self.assertLess(t.stop, t.ref_lo)
        self.assertEqual(t.result, "target")
        self.assertGreater(t.r, 1.5)

    def test_not_filled_and_against_the_trend(self):
        bars = day_bars({"04:00": (19970, 19972), "04:05": (19971, 19990), "04:10": (19989, 19998),
                         "05:00": (19995, 19996), "05:05": (19995, 20004), "05:10": (19999, 20005),
                         "06:00": (20004, 20015), "06:05": (20012, 20030)})              # never comes back
        self.assertEqual(mrs8.run_day(bars, D, self.s).why, "limit not filled by 8:00")
        trend = copy.deepcopy(self.s)
        trend["trend_filter"] = "1h"
        self.assertTrue(mrs8.run_day(bars, D, trend).why.startswith(("against the 1h trend", "limit not filled")))

    def test_worst_case_stop_is_the_8am_candle(self):
        flat = [Bar(T0 + i * mrs8.FIFTEEN, 100, 100.5, 99.5, 100) for i in range(40)]   # no structure at all
        t = T0 + 40 * mrs8.FIFTEEN
        self.assertEqual(mrs8.find_stop(True, 100, 90, 110, flat, flat, t, self.s), (90, "8:00 candle"))
        self.assertEqual(mrs8.find_stop(False, 100, 90, 110, flat, flat, t, self.s), (110, "8:00 candle"))
        self.assertIsNone(mrs8.find_stop(True, 100, 98, 102, flat, flat, t, self.s)[0])   # 2 pts: under 5 min
        self.assertEqual(mrs8.find_stop(True, 100, 90, 110, [], [], T0, self.s), (None, "not enough 15m history"))

    def test_setups_start_at_605(self):
        bars = day_bars({"04:00": (19970, 19972), "04:05": (19971, 19990), "04:10": (19989, 19998),
                         "05:00": (19995, 19996), "05:05": (19995, 20004), "05:10": (19999, 20005),
                         "06:00": (20004, 20015), "06:05": (20014, 20016),
                         "06:10": (19999, 20003), "06:15": (20002, 20060)})
        s = copy.deepcopy(self.s)
        s["window"]["breakouts_from"] = "06:05"
        t = mrs8.run_day(bars, D, s).trade
        self.assertEqual(t.break_at[11:16], "06:05")                           # the 6:00 close doesn't count

    def test_break_even_at_1r(self):
        bars = day_bars({"04:00": (19970, 19972), "04:05": (19971, 19990), "04:10": (19989, 19998),
                         "05:00": (19995, 19996), "05:05": (19995, 20004), "05:10": (19999, 20005),
                         "06:00": (20004, 20015), "06:05": (20012, 20012), "06:10": (19999, 20003),
                         "06:15": (20002, 20035), "06:20": (19960, 19962)})          # +1R, then through the stop
        s = copy.deepcopy(self.s)
        s["target"]["mode"] = "flat"
        plain = mrs8.run_day(bars, D, s).trade
        s["exit"] = {"breakeven_at_r": 1.0}
        be = mrs8.run_day(bars, D, s).trade
        self.assertEqual(plain.result, "stop")
        self.assertEqual((be.result, be.exit), ("be_stop", be.entry))
        self.assertGreater(be.r, plain.r)

    def test_no_breakout(self):
        bars = day_bars({"05:00": (19900, 19905), "05:05": (19900, 20100), "05:10": (19950, 20000)})
        self.assertEqual(mrs8.run_day(bars, D, self.s).why, "no breakout by 8:00")


class TargetTest(unittest.TestCase):
    def h(self, i, o, hi, lo, c):
        return Bar(T0 + i * mrs8.HOUR, o, hi, lo, c)

    def test_1h_swing_or_unfilled_fvg_whichever_is_nearer(self):
        s = copy.deepcopy(S)
        # a 1h swing high at 130 (bar 2), then a gap down leaving an unfilled FVG 112..118 (bars 4-6)
        h1 = [self.h(0, 100, 105, 99, 104), self.h(1, 104, 110, 103, 109), self.h(2, 109, 130, 108, 125),
              self.h(3, 125, 126, 118, 119), self.h(4, 119, 121, 118, 120), self.h(5, 120, 120, 105, 106),
              self.h(6, 106, 112, 100, 101), self.h(7, 101, 103, 99, 100), self.h(8, 100, 102, 98, 99)]
        t = T0 + 9 * mrs8.HOUR
        price, src = mrs8.find_target_1h(True, 100, 5, h1, t, s)       # 1R = 5: FVG at 2.4R, swing at 6R
        self.assertEqual((price, src[:6]), (112, "1h FVG"))
        price, src = mrs8.find_target_1h(True, 100, 2, h1, t, s)       # 1R = 2: FVG at 6R (> 4R): no level
        self.assertEqual((price, src), (104, "2R"))
        price, src = mrs8.find_target_1h(True, 100, 8, h1, t, s)       # 1R = 8: FVG 1.5R (< 2R), swing 3.75R
        self.assertEqual((price, src[:13]), (130, "1h swing high"))


if __name__ == "__main__":
    unittest.main()
