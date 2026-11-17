"""Replays TSLA on Mon 2026-10-19 (saved data from day-trader-skill) through the whole pipeline."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app import paths, pipeline, settings, strategies

FIX = paths.SKILL_DIR / "tests" / "fixtures"
TSLA = pipeline.Offline(
    entry=FIX / "trader-entry" / "TSLA-2026-10-19-5m.json",
    timemachine=FIX / "trader-timemachine" / "TSLA-60d5m.json.gz",
    news=FIX / "trader-news",
)


def orb(**changes):
    """The ORB bot with some settings changed (the saved config is never touched)."""
    s = strategies.load("orb")
    data = copy.deepcopy(s.settings)
    for k, v in changes.items():
        data[k] = v
    return strategies.Strategy(s.id, s.name, s.enabled, data)


class PipelineReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()

    def tearDown(self):
        self.tmp.cleanup()

    def run_tsla(self, strategy, now):
        return pipeline.run_signal(strategy, "tsla", self.rules, now=now, offline=TSLA,
                                   runs_root=self.root)

    def test_known_plan_without_volume_filter(self):
        """The repo's worked example: 364.18 at 10:15, stop 358.32, 8 shares."""
        r = self.run_tsla(orb(min_volume_x=None), "2026-10-19 10:15")
        self.assertEqual(r.status, "pass", r.reason)
        self.assertEqual(r.entry["trigger"]["price"], 364.18)
        self.assertEqual(r.entry["trigger"]["time"], "10:15 AM")
        self.assertEqual(r.plan["stop"], 358.32)
        self.assertEqual(r.plan["target"], 375.90)          # 2R, the v1 setting
        self.assertEqual(r.order["qty"], "8")
        self.assertEqual(r.order["order_class"], "bracket")
        self.assertEqual(r.risk["verdict"], "PASS")
        self.assertAlmostEqual(r.risk["max_loss"], 46.88)

    def test_v1_volume_filter_moves_the_trigger(self):
        """With 1.0x volume (v1), the thin 10:10 bar doesn't count; the 10:30 bar does."""
        r = self.run_tsla(orb(), "2026-10-19 10:40")
        self.assertEqual(r.status, "pass", r.reason)
        self.assertEqual(r.entry["trigger"]["time"], "10:35 AM")
        self.assertEqual(r.entry["trigger"]["price"], 365.75)

    def test_v1_volume_filter_is_still_waiting_at_1015(self):
        r = self.run_tsla(orb(), "2026-10-19 10:15")
        self.assertEqual(r.status, "waiting")
        self.assertIsNone(r.plan)

    def test_1r_target(self):
        r = self.run_tsla(orb(min_volume_x=None, exit={"stop": "or-mid", "target": "1R"}),
                          "2026-10-19 10:15")
        self.assertEqual(r.plan["target"], 370.04)

    def test_waiting_before_the_breakout(self):
        r = self.run_tsla(orb(min_volume_x=None), "2026-10-19 10:12")
        self.assertEqual(r.status, "waiting")
        self.assertEqual(list(r.steps), ["entry"])        # nothing after the entry ran

    def test_time_machine_and_news_attached(self):
        r = self.run_tsla(orb(min_volume_x=None), "2026-10-19 10:15")
        tm = r.data("timemachine")
        self.assertEqual(tm["mc"]["replays"], 10000)
        self.assertIn("verdict", tm)
        self.assertTrue(any(i["ticker"] == "TSLA" for i in r.data("news")["items"]))

    def test_each_signal_gets_its_own_folder(self):
        r = self.run_tsla(orb(min_volume_x=None), "2026-10-19 10:15")
        self.assertEqual(r.folder, self.root / "2026-10-19" / "orb" / "TSLA")
        for f in ("config.json", "entry.json", "plan.json", "timemachine.json", "orders.json"):
            self.assertTrue((r.folder / "trader" / f).exists(), f)
        cfg = json.loads((r.folder / "trader" / "config.json").read_text())
        self.assertIs(cfg["paper"], True)
        self.assertTrue((self.root / "2026-10-19" / "state").is_dir())   # shared per day

    def test_stop_too_far_for_max_loss_is_refused(self):
        rules = dict(self.rules, max_loss_per_trade_usd=5)   # 5.86 a share > $5
        r = pipeline.run_signal(orb(min_volume_x=None), "TSLA", rules, now="2026-10-19 10:15",
                                offline=TSLA, runs_root=self.root)
        self.assertEqual(r.status, "refused")
        self.assertIn("budget", r.reason)


if __name__ == "__main__":
    unittest.main()
