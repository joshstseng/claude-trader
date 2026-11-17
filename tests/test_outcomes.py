"""The outcome engine: target / stop / flat, gaps, ties, costs, early closes, and TSLA's real day."""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

from app import outcomes, tradelog
from app.outcomes import NY, Bar, resolve

FIX = Path(__file__).parent / "fixtures"
DAY = datetime(2026, 10, 19, tzinfo=NY).date()
ENTRY_AT = datetime(2026, 10, 19, 10, 15, tzinfo=NY)          # trigger bar (10:10) closed at 10:15
PLAN = dict(entry=100.0, stop=98.0, target=104.0, entry_at=ENTRY_AT)   # risk 2.00, target 2R


def bars(start: str, *ohlc, day=DAY):
    t = datetime.combine(day, dtime.fromisoformat(start), tzinfo=NY)
    return [Bar(t + timedelta(minutes=5 * i), *x) for i, x in enumerate(ohlc)]


def quiet_day(until="15:55", start="10:15", last_close=100.6):
    """Bars that never reach the stop or the target, through `until`."""
    t = datetime.combine(DAY, dtime.fromisoformat(start), tzinfo=NY)
    end = datetime.combine(DAY, dtime.fromisoformat(until), tzinfo=NY)
    out = []
    while t < end:
        out.append(Bar(t, 100.0, 101.0, 99.0, 100.2))
        t += timedelta(minutes=5)
    out[-1] = Bar(out[-1].start, 100.2, 101.0, 99.0, last_close)
    return out


class ResolveTest(unittest.TestCase):
    def test_target_first(self):
        o = resolve(**PLAN, bars=bars("10:15", (100, 101, 99.5, 100.5), (100.5, 104.2, 100.2, 104.0)))
        self.assertEqual((o.result, o.exit_price, o.exit_time), ("target", 104.0, "10:25"))
        self.assertEqual((o.r_gross, o.r_net, o.bars_held), (2.0, 2.0, 2))
        self.assertEqual((o.mfe_r, o.mae_r), (2.0, -0.25))

    def test_stop_first(self):
        o = resolve(**PLAN, bars=bars("10:15", (100, 100.5, 97.9, 98.5), (98.5, 105, 98.4, 104.5)))
        self.assertEqual((o.result, o.exit_price, o.exit_time, o.r_gross), ("stop", 98.0, "10:20", -1.0))

    def test_both_in_one_bar_counts_as_a_stop(self):
        o = resolve(**PLAN, bars=bars("10:15", (100, 104.5, 97.5, 101)))
        self.assertEqual((o.result, o.r_gross), ("stop", -1.0))

    def test_gap_below_the_stop_fills_at_the_open(self):
        o = resolve(**PLAN, bars=bars("10:15", (100, 100.2, 99, 99.5), (97, 97.5, 96.5, 97.2)))
        self.assertEqual((o.result, o.exit_price, o.r_gross), ("stop", 97.0, -1.5))
        self.assertEqual(o.mae_r, -1.5)

    def test_neither_is_flat_at_355(self):
        day = quiet_day() + bars("15:55", (100.6, 110, 90, 105), (105, 120, 80, 85))  # after flat-by: ignored
        o = resolve(**PLAN, bars=day)
        self.assertEqual((o.result, o.exit_price, o.exit_time), ("flat", 100.6, "15:55"))
        self.assertEqual(o.r_gross, 0.3)
        self.assertEqual((o.mfe_r, o.mae_r), (0.5, -0.5))

    def test_trigger_bar_and_earlier_bars_dont_count(self):
        day = bars("10:10", (99, 100.5, 97.0, 100)) + bars("10:15", (100, 104.5, 99.9, 104.2))
        self.assertEqual(resolve(**PLAN, bars=day).result, "target")

    def test_no_bars_after_entry(self):
        o = resolve(**PLAN, bars=bars("09:30", (99, 100, 98.5, 99.5)))
        self.assertEqual((o.result, o.r_net, o.bars_held), ("no_data", None, 0))

    def test_early_close_day_is_flat_at_1255(self):
        o = resolve(**PLAN, bars=quiet_day(until="13:00", last_close=101.0), flat_by=dtime(12, 55))
        self.assertEqual((o.result, o.exit_time), ("flat", "12:55"))
        self.assertEqual(o.exit_price, 100.2)       # the 12:50 bar's close, not the 12:55 bar

    def test_costs_come_off_both_sides(self):
        o = resolve(**PLAN, bars=bars("10:15", (100, 104.2, 99.9, 104)), qty=10, cost_pct=0.0003)
        # 0.03% x (100 + 104) = $0.0612 a share; net 3.9388 a share; 3.9388 / 2.00 risk = 1.969R
        self.assertEqual((o.r_gross, o.r_net), (2.0, 1.969))
        self.assertEqual((o.pnl_usd, o.cost_usd), (39.39, 0.61))

    def test_a_backwards_plan_is_refused(self):
        with self.assertRaises(ValueError):
            resolve(entry=100, stop=101, target=104, entry_at=ENTRY_AT, bars=[])

    def test_entry_time_formats(self):
        self.assertEqual(outcomes.entry_datetime("2026-10-19", "10:15 AM"), ENTRY_AT)
        self.assertEqual(outcomes.entry_datetime("2026-10-19", "10:15"), ENTRY_AT)


class TslaRealDayTest(unittest.TestCase):
    """TSLA, Mon 2026-10-19, Alpaca's full-day 5-minute bars."""

    @classmethod
    def setUpClass(cls):
        rows = json.loads((FIX / "alpaca-TSLA-2026-10-19-5m.json").read_text())["bars"]
        cls.bars = outcomes.bars_from_rows(rows)
        cls.close_355 = next(r["c"] for r in rows if r["t"].endswith("15:50"))   # price at 3:55 PM

    def test_v1_signal_went_flat(self):
        """The ORB bot's v1 signal (volume check on): 365.75 at 10:35, stop 358.32, target 2R 380.61."""
        o = resolve(entry=365.75, stop=358.32, target=380.61,
                    entry_at=outcomes.entry_datetime("2026-10-19", "10:35 AM"), bars=self.bars, qty=6,
                    cost_pct=0.0003)
        self.assertEqual((o.result, o.exit_time), ("flat", "15:55"))
        self.assertEqual(o.exit_price, round(self.close_355, 4))
        self.assertGreater(o.mfe_r, 0)          # it did move in our favor at some point...
        self.assertLess(o.mfe_r, 2)             # ...but never reached 2R
        self.assertGreater(o.mae_r, -1)         # and never touched the stop

    def test_repo_example_1r_target(self):
        """The repo's worked example: 364.18 at 10:15, stop 358.32, target 1R 370.04."""
        o = resolve(entry=364.18, stop=358.32, target=370.04,
                    entry_at=outcomes.entry_datetime("2026-10-19", "10:15 AM"), bars=self.bars)
        self.assertIn(o.result, ("target", "flat"))
        self.assertEqual(o.result == "target", any(b.h >= 370.04 for b in self.bars
                                                   if ENTRY_AT <= b.start < datetime(2026, 10, 19, 15, 55, tzinfo=NY)))


class TradeLogOutcomeTest(unittest.TestCase):
    def test_old_database_gets_the_new_columns(self):
        """The Railway database was made with the first version of the outcomes table."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            db = sqlite3.connect(path)
            db.executescript("""CREATE TABLE outcomes (signal_id INTEGER PRIMARY KEY, result TEXT NOT NULL,
                exit_price REAL, exit_time TEXT, r_multiple REAL, pnl_usd REAL, method TEXT NOT NULL,
                resolved_at TEXT NOT NULL); PRAGMA user_version=1;""")
            db.close()
            log = tradelog.TradeLog(path)
            cols = {r["name"] for r in log.db.execute("PRAGMA table_info(outcomes)")}
            self.assertTrue({"r_gross", "cost_usd", "mfe_r", "mae_r", "bars_held"} <= cols)
            self.assertEqual(log.db.execute("PRAGMA user_version").fetchone()[0], 2)
            log.close()


if __name__ == "__main__":
    unittest.main()
