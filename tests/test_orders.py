"""Step 1b.4: Approve → one paper bracket order, or a clear refusal. No real broker: a fake one."""

import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import pipeline, settings, strategies, tradelog
from app.account import DayAccount
from app.broker import OrderInfo
from app.orders import OrderDesk
from tests.test_pipeline import TSLA

# TSLA 2026-10-19: alert at 10:15 ET (14:15 UTC); entry 364.18, stop 358.32 (risk 5.86), target 375.90
ALERT_AT = datetime(2026, 10, 19, 14, 16, tzinfo=timezone.utc)


class FakeBroker:
    def __init__(self, price=364.50):
        self.price, self.orders, self.cancelled, self.status = price, [], [], "new"

    def last_price(self, symbol):
        return self.price

    def bracket_buy(self, symbol, qty, limit_price, stop, target, client_id):
        if any(o["client_id"] == client_id for o in self.orders):
            raise RuntimeError("client_order_id must be unique")
        self.orders.append(dict(symbol=symbol, qty=qty, limit=limit_price, stop=stop, target=target,
                                client_id=client_id))
        return OrderInfo("b-" + client_id, client_id, "accepted", 0, None)

    def order(self, client_id):
        o = next((x for x in self.orders if x["client_id"] == client_id), None)
        if o is None:
            return None
        filled = self.status == "filled"
        return OrderInfo("b-" + client_id, client_id, self.status, o["qty"] if filled else 0,
                         o["limit"] - 0.05 if filled else None)

    def cancel(self, broker_id):
        self.cancelled.append(broker_id)


def orb_settings(**orders):
    s = copy.deepcopy(strategies.load("orb").settings)
    s["min_volume_x"] = None
    s["orders"]["enabled"] = True            # on for these tests, whatever the deployed config says
    s["orders"].update(orders)
    return s


class OrderDeskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()
        self.log = tradelog.TradeLog(self.root / "t.db")
        s = orb_settings()
        strat = strategies.Strategy("orb", "ORB", True, s)
        result = pipeline.run_signal(strat, "TSLA", self.rules, now="2026-10-19 10:15", offline=TSLA,
                                     runs_root=self.root / "runs", with_news=False)
        run = self.log.start_run("orb", "live", {}, date_from="2026-10-19", date_to="2026-10-19")
        self.sid = self.log.record_signal(run, result)
        self.log.record_alert(self.sid, sent=True)
        self.log.db.execute("UPDATE alerts SET at = ? WHERE signal_id = ?", (ALERT_AT.isoformat(), self.sid))
        self.log.db.commit()
        self.broker = FakeBroker()

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def desk(self, minutes_after=1, **orders):
        return OrderDesk(self.log, self.broker, orb_settings(**orders), self.rules, runs_root=self.root / "runs",
                         now=lambda: ALERT_AT + timedelta(minutes=minutes_after))

    def test_approve_places_one_bracket_order(self):
        out = self.desk().approve(self.sid, user_id=1)
        self.assertTrue(out.placed, out.text)
        self.assertEqual(len(self.broker.orders), 1)
        o = self.broker.orders[0]
        # limit = 364.18 + min(0.1 x 5.86, 0.1% x 364.18) = 364.18 + 0.36 = 364.54; sized at the limit:
        # $50 / (364.54 - 358.32) = 8 shares
        self.assertEqual((o["symbol"], o["limit"], o["stop"], o["target"], o["qty"]),
                         ("TSLA", 364.54, 358.32, 375.90, 8))
        self.assertEqual(o["client_id"], f"orb-2026-10-19-{self.sid}")
        self.assertIn("Order sent", out.text)
        self.assertEqual((out.state, out.line), ("live", "⏳ **TSLA** · order sent: buy 8 at limit $364.54 · "
                                                         "stop $358.32 · target $375.90"))
        acct = DayAccount.for_day(self.root / "runs", "2026-10-19", self.rules)
        self.assertEqual(acct.entries_today, 1)                   # counts from the moment it's placed
        self.assertEqual(self.log.order_for_signal(self.sid)["status"], "submitted")
        self.assertEqual(self.log.latest_response(self.sid)["action"], "took")

    def test_a_second_tap_never_places_a_second_order(self):
        d = self.desk()
        d.approve(self.sid)
        out = d.approve(self.sid)
        self.assertFalse(out.placed)
        self.assertEqual(len(self.broker.orders), 1)

    def test_stale_by_time(self):
        out = self.desk(minutes_after=7).approve(self.sid)
        self.assertFalse(out.placed)
        self.assertIn("stale: the alert is 7 minutes old", out.text)
        self.assertEqual(out.state, "done")
        self.assertTrue(out.line.startswith("⛔ Not placed (stale"))
        self.assertEqual(self.broker.orders, [])

    def test_stale_by_price(self):
        self.broker.price = 366.00                                # > 364.18 + 0.25 x 5.86 = 365.645
        out = self.desk().approve(self.sid)
        self.assertIn("the price ran", out.text)
        self.assertEqual(self.broker.orders, [])

    def test_below_the_stop(self):
        self.broker.price = 358.00
        self.assertIn("at or below the stop", self.desk().approve(self.sid).text)

    def test_risk_check_runs_again_on_the_real_account(self):
        acct = DayAccount.for_day(self.root / "runs", "2026-10-19", self.rules)
        for s in ("AAA", "BBB", "CCC"):
            acct.record_entry(s, 1, 10.0, 5.0)
        out = self.desk().approve(self.sid)
        self.assertFalse(out.placed)
        self.assertIn("risk check: trades: 3 entries placed today", out.text)
        self.assertEqual(self.broker.orders, [])

    def test_paused_bot_refuses_approvals(self):
        d = self.desk()
        d.pause_source = lambda: True                              # /pause or /flatten
        out = d.approve(self.sid)
        self.assertIn("paused", out.text)
        self.assertEqual(out.state, "active")                      # the card stays: /resume and tap again
        self.assertEqual(self.broker.orders, [])

    def test_orders_switched_off_only_records(self):
        out = self.desk(enabled=False).approve(self.sid)
        self.assertFalse(out.placed)
        self.assertIn("switched off", out.text)
        self.assertEqual(self.broker.orders, [])
        self.assertEqual(self.log.latest_response(self.sid)["action"], "took")

    def test_replay_alerts_never_order(self):
        out = self.desk().approve(self.sid, source="replay")
        self.assertIn("no order is placed", out.text)
        self.assertEqual(self.broker.orders, [])

    def test_unfilled_entry_is_cancelled_and_uncounted(self):
        d = self.desk()
        cid = d.approve(self.sid).client_id
        out = d.check_entry(cid)
        self.assertIn("Not filled", out.text)
        self.assertEqual(self.broker.cancelled, ["b-" + cid])
        acct = DayAccount.for_day(self.root / "runs", "2026-10-19", self.rules)
        self.assertEqual((acct.entries_today, acct.cash), (0, 5000.0))
        self.assertEqual(self.log.order_for_signal(self.sid)["status"], "cancelled")

    def test_filled_entry_is_kept(self):
        d = self.desk()
        cid = d.approve(self.sid).client_id
        self.broker.status = "filled"
        out = d.check_entry(cid)
        self.assertIn("Filled", out.text)
        row = self.log.order_for_signal(self.sid)
        self.assertEqual((row["status"], row["filled_qty"], row["filled_price"]), ("filled", 8, 364.49))


if __name__ == "__main__":
    unittest.main()
