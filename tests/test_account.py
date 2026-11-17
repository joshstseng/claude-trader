"""Step 1b.3: the simulated $5k day account, enforced by the skill's own risk check."""

import tempfile
import unittest
from pathlib import Path

from app import pipeline, settings
from app.account import DayAccount
from tests.test_pipeline import TSLA, orb

DAY, NOW = "2026-10-19", "2026-10-19 10:15"     # TSLA: 8 shares at 364.18, max loss $46.88, cost $2,913.44


class AccountRiskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()
        self.acct = DayAccount.for_day(self.root, DAY, self.rules)

    def tearDown(self):
        self.tmp.cleanup()

    def tsla(self):
        return pipeline.run_signal(orb(min_volume_x=None), "TSLA", self.rules, now=NOW, offline=TSLA,
                                   runs_root=self.root, with_news=False)

    def test_fresh_account_passes(self):
        self.assertEqual((self.acct.cash, self.acct.entries_today), (5000.0, 0))
        self.assertEqual(self.tsla().status, "pass")

    def test_a_4th_trade_is_blocked(self):
        for sym in ("AAA", "BBB", "CCC"):
            self.acct.record_entry(sym, 1, 10.0, 5.0)
            self.acct.record_exit(sym, 10.0)                      # closed: cash is free again
        r = self.tsla()
        self.assertEqual(r.status, "blocked")
        self.assertIn("trades: 3 entries placed today", r.reason)

    def test_the_daily_loss_limit_counts_max_losses_at_the_stops(self):
        self.acct.record_entry("AAA", 10, 20.0, 50.0)
        self.acct.record_exit("AAA", 25.0)                        # a winner still counts its max loss
        self.acct.record_entry("BBB", 10, 20.0, 60.0)
        self.acct.record_exit("BBB", 20.0)
        r = self.tsla()                                           # 110 + 46.88 > 150
        self.assertEqual(r.status, "blocked")
        self.assertIn("daily loss", r.reason)

    def test_cash_for_open_positions(self):
        self.acct.record_entry("AAA", 30, 100.0, 40.0)            # $3,000 still open
        r = self.tsla()                                           # + $2,913 > $4,500 available
        self.assertEqual(r.status, "blocked")
        self.assertIn("cash", r.reason)
        self.acct.record_exit("AAA", 101.0)                       # closed: its cash is back
        self.assertEqual(self.tsla().status, "pass")

    def test_an_entry_that_never_filled_doesnt_count(self):
        for sym in ("AAA", "BBB", "CCC"):
            self.acct.record_entry(sym, 1, 10.0, 5.0)
        self.acct.cancel_entry("CCC")
        self.acct.record_exit("AAA", 10.0)
        self.acct.record_exit("BBB", 10.0)
        self.assertEqual(self.acct.entries_today, 2)
        self.assertEqual(self.tsla().status, "pass")

    def test_pnl_and_the_record_survive_a_restart(self):
        self.acct.record_entry("AAA", 10, 50.0, 20.0, signal_id=7)
        self.acct.record_exit("AAA", 52.5)
        again = DayAccount.for_day(self.root, DAY, self.rules)     # e.g. after a redeploy
        self.assertEqual((again.realized_pnl, again.cash, again.entries_today), (25.0, 5000.0, 1))
        self.assertEqual([r["kind"] for r in again.records], ["entry", "exit"])

    def test_each_day_starts_with_5000(self):
        self.acct.record_entry("AAA", 30, 100.0, 40.0)
        tomorrow = DayAccount.for_day(self.root, "2026-10-20", self.rules)
        self.assertEqual((tomorrow.cash, tomorrow.entries_today), (5000.0, 0))


if __name__ == "__main__":
    unittest.main()
