"""Snap (app/strategies/snap.py): the signal, one trade's life, and the backtest's pass bar."""

import copy
import json
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import paths
from app.research.data import D
from app.research.evaluate import Trade, verdict
from app.strategies import snap

S = json.loads((paths.STRATEGY_CONFIG_DIR / "snap.json").read_text())
NY = ZoneInfo("America/New_York")
T0 = datetime(2024, 1, 2, tzinfo=NY)


def series(closes, rng=1.0):
    """Daily bars from closes: open = previous close, high/low = close ± rng."""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(D(T0 + timedelta(days=i), prev, max(prev, c) + rng, min(prev, c) - rng, c))
        prev = c
    return out


class SnapTest(unittest.TestCase):
    def setUp(self):
        self.s = copy.deepcopy(S)
        self.s["fills"] = {"mode": "close"}           # most tests check the at-the-close machinery

    def test_config_is_off_and_not_a_live_bot(self):
        from app.strategies import KNOWN
        self.assertFalse(S["enabled"])
        self.assertEqual(S["fills"]["mode"], "next_open")            # the default since 2026-11-20
        self.assertNotIn("snap", KNOWN)                   # never started by the bot runner

    def test_buys_a_dip_in_an_uptrend_and_sells_the_snap_back(self):
        closes = [100 + i * 0.5 for i in range(220)]       # a steady uptrend
        closes += [closes[-1] - 4, closes[-1] - 8]         # two sharp down days: RSI(2) collapses
        closes += [closes[-1] + 6, closes[-1] + 8]         # the snap-back
        trades = snap.run_symbol("QQQ", series(closes), self.s)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertTrue(t.why_in.startswith(("RSI(2)", "IBS")))
        self.assertEqual(t.why_out, "close above the 5-day average")
        self.assertGreater(t.pnl_usd, 0)
        self.assertAlmostEqual((t.entry - t.stop) * t.shares, 500, delta=1)   # 1% of $50k at the stop

    def test_no_buy_below_the_200_day_average(self):
        closes = [300 - i * 0.5 for i in range(220)] + [180, 172, 175, 180]  # a downtrend, then a dip
        self.assertEqual(snap.run_symbol("QQQ", series(closes), self.s), [])

    def test_stop_and_gap(self):
        closes = [100 + i * 0.5 for i in range(220)]
        bars = series(closes + [closes[-1] - 4, closes[-1] - 8])
        last = bars[-1].c
        bars.append(D(bars[-1].t + timedelta(days=1), last - 30, last - 29, last - 40, last - 35))   # gaps through
        t = snap.run_symbol("QQQ", bars, self.s)[0]
        self.assertEqual(t.why_out, "stop")
        self.assertLess(t.exit, t.stop)                    # filled at the gap's open, below the stop
        self.assertLess(t.r, -1.0)

    def test_next_open_mode_buys_and_sells_at_the_next_open(self):
        closes = [100 + i * 0.5 for i in range(220)]
        closes += [closes[-1] - 4, closes[-1] - 8, closes[-1] + 6, closes[-1] + 8, closes[-1] + 9]
        bars = series(closes)
        self.s["fills"] = {"mode": "next_open"}
        t = snap.run_symbol("QQQ", bars, self.s)[0]
        signal_day = next(i for i, b in enumerate(bars) if b.t.date().isoformat() > t.day_in) - 1
        self.assertAlmostEqual(t.entry, bars[signal_day].o * 1.0001, places=3)    # the next day's open
        out = next(i for i, b in enumerate(bars) if b.t.date().isoformat() == t.day_out)
        self.assertAlmostEqual(t.exit, bars[out].o * 0.9999, places=3)            # sold at an open too

    def test_plan_next(self):
        up = [100 + i * 0.5 for i in range(220)]
        dip = series(up + [up[-1] - 4, up[-1] - 8])                 # today: a dip in an uptrend
        flat = series(up)
        plan = {x["sym"]: x for x in snap.plan_next({"QQQ": dip, "SPY": flat}, self.s)}
        self.assertEqual(plan["QQQ"]["action"], "buy")
        self.assertGreater(plan["QQQ"]["shares"], 0)
        self.assertEqual(plan["SPY"]["action"], "none")
        held = series(up + [up[-1] - 4, up[-1] - 8, up[-1] - 9])     # bought at today's open, still down
        self.assertEqual(snap.plan_next({"QQQ": held}, self.s)[0]["action"], "hold")
        back = series(up + [up[-1] - 4, up[-1] - 8, up[-1] - 9, up[-1] + 5])   # snapped back above the 5-day avg
        self.assertEqual(snap.plan_next({"QQQ": back}, self.s)[0]["action"], "sell")

    def test_the_pass_bar(self):
        mk = lambda y, p: Trade("X", 1, datetime(y, 6, 1), datetime(y, 6, 2), 100, 100 + p, 1)   # noqa: E731
        good = [mk(y, p) for y in range(2021, 2027) for p in (30, 30, -10) * 6]
        ok, v = verdict(good)
        self.assertTrue(ok, v["checks"])
        bad = [mk(y, p) for y in range(2021, 2027) for p in (10, -10) * 10]
        self.assertFalse(verdict(bad)[0])


if __name__ == "__main__":
    unittest.main()
