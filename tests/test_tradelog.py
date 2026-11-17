import copy
import json
import tempfile
import unittest
from pathlib import Path

from app import pipeline, settings, strategies, tradelog
from tests.test_pipeline import TSLA


def orb_without_volume_filter():
    s = strategies.load("orb")
    data = copy.deepcopy(s.settings)
    data["min_volume_x"] = None
    return strategies.Strategy(s.id, s.name, s.enabled, data)


class TradeLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # one real replay, shared by every test (the pipeline is the slow part)
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.rules = settings.risk_rules()
        cls.orb = orb_without_volume_filter()
        cls.tsla = pipeline.run_signal(cls.orb, "TSLA", cls.rules, now="2026-10-19 10:15",
                                       offline=TSLA, runs_root=root / "runs")
        cls.waiting = pipeline.run_signal(cls.orb, "TSLA", cls.rules, now="2026-10-19 10:12",
                                          offline=TSLA, runs_root=root / "runs-waiting",
                                          with_news=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.dbdir = tempfile.TemporaryDirectory()
        self.log = tradelog.TradeLog(Path(self.dbdir.name) / "t.db")
        self.run_id = self.log.start_run("orb", "replay", {"strategy": self.orb.settings,
                                                            "risk": self.rules},
                                         label="TSLA 2026-10-19", date_from="2026-10-19",
                                         date_to="2026-10-19")

    def tearDown(self):
        self.log.close()
        self.dbdir.cleanup()

    def test_run_stores_settings_snapshot_and_tags(self):
        run = self.log.run(self.run_id)
        self.assertEqual((run["strategy"], run["source"]), ("orb", "replay"))
        snap = json.loads(run["settings_json"])
        self.assertEqual(snap["strategy"]["exit"]["target"], "2R")
        self.assertIs(snap["risk"]["paper"], True)

    def test_bad_source_rejected(self):
        with self.assertRaises(ValueError):
            self.log.start_run("orb", "paper-ish", {})

    def test_signal_saved_with_full_plan(self):
        sid = self.log.record_signal(self.run_id, self.tsla)
        s = self.log.signal(sid)
        self.assertEqual((s["strategy"], s["source"], s["symbol"], s["date"]),
                         ("orb", "replay", "TSLA", "2026-10-19"))
        self.assertEqual(s["status"], "pass")
        self.assertEqual((s["trigger_time"], s["trigger_price"]), ("10:15", 364.18))
        self.assertEqual((s["or_high"], s["or_low"]), (362.18, 354.47))
        self.assertEqual((s["entry"], s["stop"], s["target"], s["target_r"]),
                         (364.18, 358.32, 375.90, 2.0))
        self.assertEqual((s["qty"], s["max_loss"], s["risk_verdict"]), (8, 46.88, "PASS"))
        self.assertAlmostEqual(s["tm_p_target"], 0.0397)
        self.assertIn("toward the stop", s["tm_verdict"])

    def test_waiting_is_not_a_signal(self):
        with self.assertRaises(ValueError):
            self.log.record_signal(self.run_id, self.waiting)

    def test_rerun_replaces_instead_of_duplicating(self):
        a = self.log.record_signal(self.run_id, self.tsla)
        b = self.log.record_signal(self.run_id, self.tsla)
        self.assertEqual(a, b)
        self.assertEqual(len(self.log.signals(run_id=self.run_id)), 1)

    def test_query_by_strategy_source_and_date(self):
        self.log.record_signal(self.run_id, self.tsla)
        self.assertEqual(len(self.log.signals(strategy="orb", source="replay", date="2026-10-19")), 1)
        self.assertEqual(len(self.log.signals(source="live")), 0)

    def test_alerts_and_daily_cap_count(self):
        sid = self.log.record_signal(self.run_id, self.tsla)
        self.log.record_alert(sid, sent=True, channel_id=1, message_id=2)
        self.assertEqual(self.log.alerts_sent(strategy="orb", date="2026-10-19", source="replay"), 1)
        self.assertEqual(self.log.alerts_sent(strategy="orb", date="2026-10-19", source="live"), 0)
        with self.assertRaises(ValueError):
            self.log.record_alert(sid, sent=False)   # held back needs a reason

    def test_last_response_wins(self):
        sid = self.log.record_signal(self.run_id, self.tsla)
        self.log.record_response(sid, "skip", user_id=7)
        self.log.record_response(sid, "took", user_id=7)
        self.assertEqual(self.log.latest_response(sid)["action"], "took")

    def test_outcome_computes_r_and_dollars_from_the_plan(self):
        sid = self.log.record_signal(self.run_id, self.tsla)
        self.assertEqual(len(self.log.unresolved(strategy="orb", date="2026-10-19")), 1)
        self.log.record_outcome(sid, result="stop", exit_price=358.32, exit_time="11:05",
                                method="test")
        o = self.log.outcome(sid)
        self.assertEqual(o["r_multiple"], -1.0)
        self.assertEqual(o["pnl_usd"], -46.88)
        self.assertEqual(len(self.log.unresolved(strategy="orb", date="2026-10-19")), 0)


if __name__ == "__main__":
    unittest.main()
