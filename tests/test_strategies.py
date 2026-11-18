"""Step 2b.1: strategies plug in through a brain; the ORB bot is the first of many."""

import copy
import gzip
import io
import json
import logging
import tempfile
import unittest
from datetime import date, time as dtime
from pathlib import Path

from app import logs, outcomes, paths, pipeline, settings, strategies
from app.backtest import signals
from app.market import Session
from app.settings import SettingsError
from app.strategies.demo import DemoBrain
from app.strategies.orb import OrbBrain

WALL = paths.SKILL_DIR / "tests" / "fixtures" / "trader-scanner" / "wall5m-2026-10-19.json.gz"
OCT19 = Session(date(2026, 10, 19), dtime(9, 30), dtime(16, 0))


class RegistryTest(unittest.TestCase):
    def tearDown(self):
        strategies.set_active("orb")

    def test_orb_is_the_orb_brain_with_its_tag(self):
        orb = strategies.load("orb")
        self.assertIsInstance(orb.brain, OrbBrain)
        self.assertEqual(orb.tag, "ORB")

    def test_demo_is_listed_but_switched_off(self):
        demo = strategies.load("demo")
        self.assertIsInstance(demo.brain, DemoBrain)
        self.assertFalse(demo.enabled)
        self.assertEqual([s.id for s in strategies.load_enabled()], ["orb"])

    def test_unknown_strategy(self):
        with self.assertRaises(SettingsError):
            strategies.set_active("nope")

    def test_active_tag_defaults_to_orb(self):
        self.assertEqual(strategies.tag(), "ORB")
        strategies.set_active("demo")
        self.assertEqual(strategies.tag(), "DEMO")

    def test_log_lines_carry_the_bot_tag(self):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        h.setFormatter(logging.Formatter("[%(bot)s] %(message)s"))
        h.addFilter(logs.BotTag())
        lg = logging.getLogger("tag-test")
        lg.addHandler(h)
        lg.warning("hello")
        lg.removeHandler(h)
        self.assertEqual(buf.getvalue().strip(), "[ORB] hello")


class OrbBrainIsUnchangedTest(unittest.TestCase):
    def test_schedule_is_the_same(self):
        b = strategies.load("orb").brain
        times = [t.strftime("%H:%M") for t in b.check_times(OCT19)]
        self.assertEqual((times[0], times[-1], len(times)), ("09:51", "11:31", 21))
        self.assertEqual(b.backtest_check_time(OCT19).strftime("%H:%M"), "11:31")
        self.assertEqual(b.premarket_at(OCT19).strftime("%H:%M"), "08:30")


class DemoStrategyPlugsInTest(unittest.TestCase):
    """A second strategy runs through the shared backtest and live pipeline without ORB code."""

    @classmethod
    def setUpClass(cls):
        wall = json.load(gzip.open(WALL, "rt"))
        cls.bars = {}
        for sym, doc in wall.items():
            try:
                cls.bars[sym] = outcomes.bars_from_yahoo(doc)
            except (KeyError, IndexError, TypeError):
                pass
        cls.demo = strategies.load("demo")

    def test_backtest(self):
        sigs = signals.generate([OCT19], lambda s: sorted(self.bars), lambda s, f: self.bars, self.demo.settings,
                                settings.risk_rules(), cost_pct=0.0003)
        self.assertGreater(len(sigs), 0)
        for s in sigs:
            self.assertLess(s.stop, s.entry)
            self.assertGreater(s.target, s.entry)
            self.assertGreaterEqual(s.trigger_time, "10:00")          # demo's window starts at 10:00
            self.assertLessEqual(s.trigger_time, "11:30")

    def test_live_pipeline(self):
        from tests.test_pipeline import TSLA
        with tempfile.TemporaryDirectory() as d:
            r = pipeline.run_signal(self.demo, "TSLA", settings.risk_rules(), now="2026-10-19 10:45", offline=TSLA,
                                    runs_root=Path(d), with_news=False)
        self.assertIn(r.status, ("pass", "blocked", "refused", "waiting", "expired"))
        if r.entry and r.entry.get("status") == "triggered":
            self.assertEqual(r.entry["setup"], "vwap")
            self.assertLess(r.plan["stop"], r.plan["entry"])


if __name__ == "__main__":
    unittest.main()
