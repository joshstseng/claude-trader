"""Step 1b.9: live trade cards and managing a trade from Discord."""

import re
import tempfile
import unittest
from datetime import datetime, time as dtime, timezone
from pathlib import Path

from app import cards, settings, tradelog
from app.account import DayAccount
from app.broker import OrderInfo
from app.livecards import TRADE_RE
from app.manage import TradeManager

DAY = "2026-11-19"


class FakeAlpaca:
    def __init__(self, price=368.40):
        self.px, self.replaced, self.cancelled, self.closed = price, [], [], []

    def price(self, symbol):
        return self.px

    def order(self, cid):
        return OrderInfo("B", cid, "new", 0, None)

    def cancel(self, bid):
        self.cancelled.append(bid)

    def replace_leg(self, leg_id, *, stop_price=None, limit_price=None):
        self.replaced.append((leg_id, stop_price, limit_price))
        return f"{leg_id}-v{len(self.replaced) + 1}"

    def close_now(self, symbol, legs):
        self.closed.append((symbol, legs))
        return "SELL1"

    def fill_of(self, oid):
        return "filled", self.px


class TradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()
        self.log = tradelog.TradeLog(self.root / "t.db")
        run = self.log.start_run("orb", "live", {}, date_from=DAY, date_to=DAY)
        self.log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop, target,"
                            " qty, created_at) VALUES (?, 'orb', 'live', ?, 'TSLA', 'pass', 365.75, 358.32, 380.61, 6,"
                            " 'x')", (run, DAY))
        self.sid = self.log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
        self.cid = f"orb-{DAY}-{self.sid}"
        self.log.add_order(self.sid, self.cid, "TSLA", 6, 366.12, 358.32, 380.61, broker_order_id="B1")
        self.log.update_order(self.cid, stop_order_id="S1", target_order_id="T1")
        DayAccount.for_day(self.root, DAY, self.rules).record_entry("TSLA", 6, 366.12, 46.8, signal_id=self.sid)
        self.alpaca = FakeAlpaca()
        self.m = TradeManager(self.alpaca, self.log, self.rules, runs_root=self.root, fill_wait_s=0.5)

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def fill(self, price=365.90):
        self.log.update_order(self.cid, status="filled", filled_qty=6, filled_price=price,
                              filled_at="2026-11-19T15:36:00+00:00")
        DayAccount.for_day(self.root, DAY, self.rules).update_fill("TSLA", 6, price)

    # ---------------------------------------------------------------- manage

    def test_cancel_an_unfilled_entry(self):
        r = self.m.cancel(self.cid)
        self.assertTrue(r.ok and r.cancelled)
        self.assertEqual(self.alpaca.cancelled, ["B1"])
        self.assertEqual(DayAccount.for_day(self.root, DAY, self.rules).entries_today, 0)
        self.assertEqual(self.log.order(self.cid)["status"], "cancelled")

    def test_cant_cancel_once_filled(self):
        self.fill()
        self.assertIn("Close now", self.m.cancel(self.cid).message)

    def test_stops_only_move_up(self):
        self.fill()
        r = self.m.move_stop(self.cid, 357.00)
        self.assertFalse(r.ok)
        self.assertIn("Stops only move up", r.message)
        self.assertEqual(self.alpaca.replaced, [])

    def test_stop_must_stay_below_the_price(self):
        self.fill()
        r = self.m.move_stop(self.cid, 368.50)                      # price is 368.40
        self.assertIn("must be below the current price", r.message)

    def test_move_stop_up_changes_the_leg_and_saves_its_new_id(self):
        self.fill()
        r = self.m.move_stop(self.cid, 362.00)
        self.assertEqual(r.message, "Stop moved: $358.32 → $362.00.")
        self.assertEqual(self.alpaca.replaced, [("S1", 362.0, None)])
        row = self.log.order(self.cid)
        self.assertEqual((row["stop"], row["stop_order_id"]), (362.0, "S1-v2"))
        self.assertEqual([(e["kind"], e["old_value"], e["new_value"]) for e in self.log.events(self.cid)],
                         [("stop_moved", 358.32, 362.0)])

    def test_breakeven(self):
        self.fill(365.90)
        r = self.m.breakeven(self.cid)
        self.assertEqual(r.message, "Stop moved to break-even: $358.32 → $365.90.")
        self.alpaca.px = 365.00                                      # below the entry now
        self.log.update_order(self.cid, stop=358.32)
        self.assertIn("must be below the current price", self.m.breakeven(self.cid).message)

    def test_move_target(self):
        self.fill()
        self.assertIn("above the current price", self.m.move_target(self.cid, 368.00).message)
        r = self.m.move_target(self.cid, 385.00)
        self.assertEqual(r.message, "Target moved: $380.61 → $385.00.")
        self.assertEqual(self.log.order(self.cid)["target_order_id"], "T1-v2")

    def test_close_now(self):
        self.fill(365.90)
        r = self.m.close(self.cid)
        self.assertTrue(r.ok and r.closed)
        self.assertEqual(self.alpaca.closed, [("TSLA", ["S1", "T1"])])
        row = self.log.order(self.cid)
        self.assertEqual((row["status"], row["exit_reason"], row["exit_price"], row["pnl_usd"]),
                         ("closed", "manual", 368.40, 15.0))
        self.assertEqual(DayAccount.for_day(self.root, DAY, self.rules).realized_pnl, 15.0)
        self.assertIn("already closed", self.m.close(self.cid).message)   # a second tap does nothing

    # ----------------------------------------------------------------- cards

    def test_waiting_card(self):
        now = datetime.fromisoformat(self.log.order(self.cid)["submitted_at"])
        title, body = cards.waiting_card(self.log.order(self.cid), now.replace(second=now.second), 120)
        self.assertEqual(title, "⏳ [ORB] TSLA · waiting for fill")
        self.assertIn("Limit **$366.12** · 6 sh · stop $358.32 · target $380.61", body)

    def test_live_card_puts_the_pnl_in_the_title(self):
        self.fill(365.90)
        self.m.breakeven(self.cid)
        row, sig = self.log.order(self.cid), self.log.signal(self.sid)
        now = datetime(2026, 11, 19, 15, 45, tzinfo=timezone.utc)   # 10:45 AM ET
        title, body, pnl = cards.live_card(row, sig, 368.40, now, dtime(15, 55), self.log.events(self.cid))
        self.assertEqual(title, "🟢 [ORB] TSLA · +$15.00 · +0.34R")         # 2.50 x 6; 2.50 / 7.43 risk
        self.assertEqual(pnl, 15.0)
        self.assertIn("6 sh · in **$365.90** at 10:36 AM ET · now **$368.40**", body)
        self.assertIn("Stop    $365.90    (−0.7% away)", body)
        self.assertIn("Target  $380.61    (+3.3% away)", body)
        self.assertIn("Sells at 3:55 PM ET (5h 10m)", body)
        self.assertIn("Changes: stop → break-even $358.32 → $365.90", body)
        self.assertNotIn("best", body.lower())                               # no best/worst move

    def test_losing_trade_is_red(self):
        self.fill(365.90)
        row, sig = self.log.order(self.cid), self.log.signal(self.sid)
        title, _, pnl = cards.live_card(row, sig, 363.00, datetime(2026, 11, 19, 15, 45, tzinfo=timezone.utc),
                                        dtime(15, 55))
        self.assertEqual(title, "🔴 [ORB] TSLA · −$17.40 · −0.39R")
        self.assertLess(pnl, 0)

    def test_system_confirmation_line(self):
        from app.livecards import confirmation
        line = confirmation("NET", "Stop moved: $287.80 → $300.00.")
        self.assertTrue(line.startswith("🔧 **[ORB] NET** · Stop moved: $287.80 → $300.00 · "))
        self.assertTrue(line.endswith(" ET"))

    def test_closed_card(self):
        self.fill(365.90)
        self.log.update_order(self.cid, status="closed", exit_reason="target", exit_price=380.61, pnl_usd=88.26,
                              exited_at="2026-11-19T18:12:00+00:00")
        row, sig = self.log.order(self.cid), self.log.signal(self.sid)
        head, body = cards.closed_card(row, sig, (), {"result": "target", "r_gross": 2.0})
        self.assertEqual(head, "✅ [ORB] TSLA · target hit · **+$88.26** · +1.98R")
        self.assertIn("In $365.90 (10:36 AM) → out $380.61 (1:12 PM) · 6 sh · held 2h 36m", body)
        self.assertIn("Backtest said: ✅ +2.00R", body)

    def test_price_forms_fit_discords_limits(self):
        """Discord refuses a form whose label is over 45 characters ("didn't respond in time")."""
        import asyncio
        from app.livecards import PriceModal

        async def build():
            return [PriceModal(None, self.cid, k, "GOOGL", 1234.56) for k in ("stop", "target")]
        for m in asyncio.run(build()):
            self.assertLessEqual(len(m.price.label), 45)
            self.assertLessEqual(len(m.price.placeholder), 100)
            self.assertLessEqual(len(m.title), 45)

    def test_closed_by_you_has_no_emoji(self):
        self.fill(365.90)
        self.log.update_order(self.cid, status="closed", exit_reason="manual", exit_price=368.40, pnl_usd=15.0,
                              exited_at="2026-11-19T16:00:00+00:00")
        head, _ = cards.closed_card(self.log.order(self.cid), self.log.signal(self.sid))
        self.assertEqual(head, "[ORB] TSLA · closed by you · **+$15.00** · +0.34R")

    def test_button_ids(self):
        m = re.fullmatch(TRADE_RE, f"trade:stop:{self.cid}")
        self.assertEqual((m["action"], m["cid"]), ("stop", self.cid))
        self.assertIsNone(re.fullmatch(TRADE_RE, "trade:sell_everything:x"))


if __name__ == "__main__":
    unittest.main()
