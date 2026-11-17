"""The backtest signal engine must make the same decisions as the live pipeline."""

import copy
import gzip
import json
import unittest
from datetime import date, datetime, time as dtime, timedelta

from app import outcomes, paths, settings, strategies
from app.backtest import signals
from app.market import Session
from app.outcomes import NY, Bar

WALL = paths.SKILL_DIR / "tests" / "fixtures" / "trader-scanner" / "wall5m-2026-10-19.json.gz"
OCT19 = Session(date(2026, 10, 19), dtime(9, 30), dtime(16, 0))

# The live pipeline's replay of Oct 19 (python -m app replay, run 1): symbol, time, entry, stop, target, shares
LIVE_OCT19 = [
    ("CDNS", "09:50", 326.74, 323.19, 333.84, 11), ("CVX", "09:50", 225.13, 224.02, 227.35, 16),
    ("HUM", "09:50", 419.27, 414.45, 428.91, 8), ("ELV", "09:55", 434.80, 428.74, 446.92, 8),
    ("EOG", "09:55", 158.82, 157.50, 161.46, 23), ("MPC", "09:55", 492.48, 482.81, 511.82, 5),
    ("MAR", "10:10", 391.11, 388.77, 395.79, 9), ("ZM", "10:10", 95.75, 95.09, 97.07, 39),
    ("AMZN", "10:15", 258.93, 256.48, 263.83, 14), ("PNC", "10:15", 218.30, 217.08, 220.74, 17),
    ("RCL", "10:15", 280.99, 277.61, 287.75, 13), ("VRTX", "10:15", 504.12, 501.76, 508.84, 7),
    ("SHOP", "10:20", 173.46, 171.47, 177.44, 21), ("HMC", "10:25", 34.09, 34.04, 34.19, 110),
    ("MSFT", "10:25", 533.53, 530.68, 539.23, 7), ("TSLA", "10:35", 365.75, 358.32, 380.61, 6),
]


def orb(**changes):
    s = strategies.load("orb")
    data = copy.deepcopy(s.settings)
    data.update(changes)
    return data


def day(*ohlcv, start="09:30"):
    t = datetime.combine(OCT19.day, dtime.fromisoformat(start), tzinfo=NY)
    return [Bar(t + timedelta(minutes=5 * i), *x) for i, x in enumerate(ohlcv)]


RANGE = [(100, 101, 99, 100.5, 1000), (100.5, 102, 100, 101.5, 1000), (101.5, 101.8, 100.8, 101, 1000)]


class MatchesLivePipelineTest(unittest.TestCase):
    def test_oct19_same_16_signals_as_the_live_pipeline(self):
        wall = json.load(gzip.open(WALL, "rt"))
        bars = {}
        for sym, doc in wall.items():
            try:
                bars[sym] = outcomes.bars_from_yahoo(doc)
            except (KeyError, IndexError, TypeError):
                pass
        sigs = signals.generate([OCT19], lambda s: sorted(bars), lambda s, f: bars, orb(),
                                settings.risk_rules(), cost_pct=0.0003)
        got = [(x.symbol, x.trigger_time, x.entry, x.stop, x.target, x.qty) for x in sigs]
        self.assertEqual(got, LIVE_OCT19)                      # same signals, same order (FCFS)


class LiveAndBacktestAgreeTest(unittest.TestCase):
    def test_full_day_through_the_live_bot_equals_the_backtest(self):
        """Step 1b.2: the live bot (every 5-minute check, Yahoo charts, scan pre-filter) and the
        backtest (one pass at the window's end) give the same signals: one engine."""
        import asyncio
        import tempfile
        from pathlib import Path
        from app import market, tradelog
        from app.routine import DayData, LogAlerter, OrbDay
        from app.scheduler import SimClock, run_day
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            log = tradelog.TradeLog(root / "t.db")
            bot = OrbDay(strategies.load("orb"), settings.risk_rules(), log, source="replay", day="2026-10-19",
                         alerter=LogAlerter(), runs_root=root / "runs",
                         day_data=DayData(bars=WALL, entry_dir=market.split_bundle(WALL, root / "bars")))
            clock = SimClock(datetime.combine(OCT19.day, dtime(7, 0), tzinfo=NY))
            asyncio.run(run_day(bot, OCT19, clock, simulated=True))
            rows = log.signals(run_id=bot.run_id)
            live = sorted((r["symbol"], r["trigger_time"], r["entry"], r["stop"], r["target"], r["qty"]) for r in rows)
            log.close()
        self.assertEqual(live, sorted(LIVE_OCT19))


class SignalRulesTest(unittest.TestCase):
    rules = settings.risk_rules()

    def run_one(self, bars, **changes):
        return signals.signal_for("XYZ", bars, OCT19, orb(**changes), self.rules, cost_pct=0.0)

    def test_close_above_range_high_with_volume_triggers(self):
        s = self.run_one(day(*RANGE, (101, 102.5, 100.9, 102.3, 1500)))
        self.assertEqual((s.status, s.trigger_time, s.entry), ("pass", "09:50", 102.3))
        self.assertEqual(s.stop, 100.5)                        # range midpoint (102 + 99) / 2
        self.assertEqual(s.target, 105.9)                      # 2R
        self.assertEqual(s.outcome["result"], "no_data")       # no bars after the entry in this test

    def test_a_wick_above_is_not_a_trigger(self):
        self.assertIsNone(self.run_one(day(*RANGE, (101, 103, 100.9, 101.9, 1500))))

    def test_thin_volume_waits_for_a_bar_with_volume(self):
        s = self.run_one(day(*RANGE, (101, 102.5, 100.9, 102.3, 500), (102.3, 102.9, 102.1, 102.8, 1200)))
        self.assertEqual((s.trigger_time, s.entry), ("09:55", 102.8))

    def test_after_the_scan_window_is_not_a_signal(self):
        quiet = [(101, 101.5, 100.5, 101, 1000)] * 20               # 9:45 .. 11:20 bars, under the high
        late = day(*RANGE, *quiet, (101, 103, 100.9, 102.9, 5000))  # the 11:25 bar closes at 11:30: in
        self.assertEqual(self.run_one(late).trigger_time, "11:30")
        later = day(*RANGE, *quiet, (101, 101.5, 100.5, 101, 1000), (101, 103, 100.9, 102.9, 5000))
        self.assertIsNone(self.run_one(later))                        # closes at 11:35: out

    def test_a_missing_bar_skips_the_stock_like_the_live_scan(self):
        bars = day(*RANGE, (101, 101.5, 100.5, 101, 1000), (101, 102.5, 100.9, 102.3, 1500))
        del bars[3]                                                   # no 9:45 bar
        self.assertIsNone(self.run_one(bars))

    def test_under_the_price_floor_is_skipped(self):
        cheap = [(o / 25, h / 25, l / 25, c / 25, v) for o, h, l, c, v in
                 [*RANGE, (101, 102.5, 100.9, 102.3, 1500)]]
        self.assertIsNone(self.run_one(day(*cheap)))

    def test_too_expensive_for_the_account_is_refused(self):
        pricey = [(o * 60, h * 60, l * 60, c * 60, v) for o, h, l, c, v in
                  [*RANGE, (101, 102.5, 100.9, 102.3, 1500)]]           # ~$6,100 a share
        s = self.run_one(day(*pricey))
        self.assertEqual(s.status, "refused")
        self.assertIn("budget", s.reason)


if __name__ == "__main__":
    unittest.main()
