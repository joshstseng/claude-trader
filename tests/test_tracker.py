"""Step 1b.5: Alpaca's order events -> the books and #trades."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from app import settings, tradelog
from app.account import DayAccount
from app.tracker import TradeTracker

DAY = "2026-11-18"


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()
        self.log = tradelog.TradeLog(self.root / "t.db")
        run = self.log.start_run("orb", "live", {}, date_from=DAY, date_to=DAY)
        # TSLA plan: entry 365.75, stop 358.32 (risk 7.43), target 380.61; order: 6 at limit 366.12
        self.log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop, target,"
                            " qty, created_at) VALUES (?, 'orb', 'live', ?, 'TSLA', 'pass', 365.75, 358.32, 380.61, 6, 'x')",
                            (run, DAY))
        self.sid = self.log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
        self.cid = f"orb-{DAY}-{self.sid}"
        self.log.add_order(self.sid, self.cid, "TSLA", 6, 366.12, 358.32, 380.61, broker_order_id="B1")
        self.log.update_order(self.cid, stop_order_id="S1", target_order_id="T1")
        DayAccount.for_day(self.root, DAY, self.rules).record_entry("TSLA", 6, 366.12, 46.8, signal_id=self.sid)
        self.t = TradeTracker(self.log, self.rules, runs_root=self.root)

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def order(self, oid, cid="", qty=6, price=None):
        return NS(id=oid, client_order_id=cid, symbol="TSLA", filled_qty=str(qty), filled_avg_price=price,
                  filled_at="2026-11-18T15:10:00Z")

    def acct(self):
        return DayAccount.for_day(self.root, DAY, self.rules)

    def test_entry_fill(self):
        u = self.t.handle("fill", self.order("B1", self.cid, price="365.90"))
        self.assertEqual(u.signal_id, self.sid)
        self.assertEqual(u.text, "🟢 **[ORB] Bought TSLA**: 6 at $365.90 · plan $365.75 (+$0.15 a share slippage) · "
                                 "stop $358.32 · target $380.61")
        row = self.log.order_for_signal(self.sid)
        self.assertEqual((row["status"], row["filled_price"], row["entry_slippage"]), ("filled", 365.9, 0.15))
        self.assertEqual((u.state, u.line), ("live", "🟢 **[ORB] TSLA** · in trade: 6 @ $365.90 · stop $358.32 · "
                                                     "target $380.61"))
        self.assertIsNone(self.t.handle("fill", self.order("B1", self.cid, price="365.90")))   # once only

    def test_stopped_out(self):
        self.t.handle("fill", self.order("B1", self.cid, price="365.90"))
        u = self.t.handle("fill", self.order("S1", "random-leg-id", price="358.20"))
        # P&L from the real fill (365.90), not the limit: (358.20 - 365.90) x 6 = -46.20; -7.70 / 7.43 risk
        self.assertIn("❌ **[ORB] Stopped out** TSLA: sold 6 at $358.20 (stop $358.32) · **−$46.20**", u.text)
        self.assertIn("−1.04R", u.text)
        self.assertEqual((u.state, u.line), ("done", "❌ [ORB] TSLA · stopped out at $358.20 · −$46.20 · −1.04R"))
        a = self.acct()
        self.assertEqual((a.open_positions, a.realized_pnl, a.cash), ([], -46.2, 5000.0))
        row = self.log.order_for_signal(self.sid)
        self.assertEqual((row["status"], row["exit_reason"], row["exit_slippage"]), ("closed", "stop", -0.12))
        self.assertIsNone(self.t.handle("fill", self.order("S1", "random-leg-id", price="358.20")))  # once only

    def test_target_hit(self):
        self.t.handle("fill", self.order("B1", self.cid, price="366.00"))
        u = self.t.handle("fill", self.order("T1", "x", price="380.61"))
        self.assertTrue(u.text.startswith("✅ **[ORB] Target hit** TSLA: sold 6 at $380.61 (target $380.61) · **+$87.66**"))

    def test_unfilled_entry_cancelled(self):
        u = self.t.handle("canceled", self.order("B1", self.cid, qty=0))
        self.assertIn("nothing bought", u.text)
        self.assertEqual(self.acct().entries_today, 0)

    def test_other_leg_cancelling_is_ignored(self):
        self.t.handle("fill", self.order("B1", self.cid, price="365.90"))
        self.t.handle("fill", self.order("T1", "x", price="380.61"))
        self.assertIsNone(self.t.handle("canceled", self.order("S1", "y", qty=0)))

    def test_orders_that_arent_ours_are_ignored(self):
        self.assertIsNone(self.t.handle("fill", self.order("FLATTEN-SELL", "random", price="367.00")))


if __name__ == "__main__":
    unittest.main()
