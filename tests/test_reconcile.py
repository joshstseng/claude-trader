"""Step 1b.7: restart safety: the books are lined up with Alpaca on every start."""

import tempfile
import unittest
from datetime import date, datetime, time as dtime
from pathlib import Path

from app import settings, tradelog
from app.account import DayAccount
from app.broker import OrderInfo
from app.market import NY, Session
from app.reconcile import Reconciler

DAY = date(2026, 11, 18)
SESSION = Session(DAY, dtime(9, 30), dtime(16, 0))


class FakeAlpaca:
    def __init__(self):
        self.orders, self.held, self.legs, self.cancelled, self.closed_all = {}, {}, {}, [], 0

    def order(self, cid):
        return self.orders.get(cid)

    def cancel(self, bid):
        self.cancelled.append(bid)

    def positions(self):
        return [{"symbol": s, "qty": q} for s, q in self.held.items()]

    def exit_fill(self, cid):
        return self.legs.get(cid)

    def close_all(self):
        self.closed_all += 1
        return [(s, None) for s in self.held]


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()
        self.log = tradelog.TradeLog(self.root / "t.db")
        self.run = self.log.start_run("orb", "live", {}, date_from=str(DAY), date_to=str(DAY))
        self.alpaca = FakeAlpaca()

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def placed(self, sym, qty=6, price=100.0, submitted=None, status="submitted"):
        self.log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop, target,"
                            " qty, created_at) VALUES (?, 'orb', 'live', ?, ?, 'pass', ?, ?, ?, ?, 'x')",
                            (self.run, str(DAY), sym, price, price - 2, price + 4, qty))
        sid = self.log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
        cid = f"orb-{DAY}-{sid}"
        self.log.add_order(sid, cid, sym, qty, price, price - 2, price + 4, broker_order_id="B" + sym)
        self.log.update_order(cid, status=status)
        if submitted:
            self.log.db.execute("UPDATE orders SET submitted_at = ? WHERE client_order_id = ?", (submitted, cid))
            self.log.db.commit()
        DayAccount.for_day(self.root, str(DAY), self.rules).record_entry(sym, qty, price, 12.0, signal_id=sid)
        return cid

    def run_at(self, hhmm, session=SESSION):
        now = datetime.combine(DAY, dtime.fromisoformat(hhmm), tzinfo=NY)
        return Reconciler(self.alpaca, self.log, self.rules, runs_root=self.root, now=lambda: now).reconcile(session)

    def acct(self):
        return DayAccount.for_day(self.root, str(DAY), self.rules)

    def test_fill_while_away_is_booked_with_the_real_price(self):
        cid = self.placed("TSLA")
        self.alpaca.orders[cid] = OrderInfo("BTSLA", cid, "filled", 6, 100.07)
        self.alpaca.held["TSLA"] = 6
        rep = self.run_at("10:40")
        self.assertIn("TSLA: entry filled while I was away (6 at $100.07)", rep.notes)
        self.assertEqual(self.acct().open_positions[0].entry_price, 100.07)
        self.assertEqual(rep.problems, [])

    def test_stop_hit_while_away_is_booked(self):
        cid = self.placed("NVDA", status="filled")
        self.alpaca.orders[cid] = OrderInfo("BNVDA", cid, "filled", 6, 100.0)
        self.alpaca.legs[cid] = ("stop", 97.9, "2026-11-18T15:02:00Z")
        rep = self.run_at("11:10")
        self.assertEqual(rep.trades, ["❌ Stopped out NVDA while I was away: 6 at $97.90 (−$12.60)"])
        self.assertEqual((self.acct().open_positions, self.acct().realized_pnl), ([], -12.6))
        self.assertEqual(self.log.order_for_signal(1)["exit_reason"], "stop")

    def test_old_unfilled_entry_is_cancelled(self):
        cid = self.placed("AMD", submitted="2026-11-18T15:00:00+00:00")       # 10:00 ET, 5 minutes ago
        self.alpaca.orders[cid] = OrderInfo("BAMD", cid, "accepted", 0, None)
        rep = self.run_at("10:05")
        self.assertIn("AMD: entry never filled, cancelled", rep.notes)
        self.assertEqual(self.alpaca.cancelled, ["BAMD"])
        self.assertEqual(self.acct().entries_today, 0)

    def test_fresh_unfilled_entry_gets_its_fill_check_back(self):
        cid = self.placed("AMD", submitted="2026-11-18T15:00:00+00:00")       # 10:00:00 ET
        self.alpaca.orders[cid] = OrderInfo("BAMD", cid, "accepted", 0, None)
        rep = self.run_at("10:01")                                             # 60 s old
        self.assertEqual(rep.recheck, [(cid, 60.0)])
        self.assertEqual(self.alpaca.cancelled, [])

    def test_held_overnight_queues_a_sell_and_pings(self):
        cid = self.placed("TSLA", status="filled")
        self.alpaca.orders[cid] = OrderInfo("BTSLA", cid, "filled", 6, 100.0)
        self.alpaca.held["TSLA"] = 6
        with self.assertLogs("app.reconcile", level="ERROR") as logs:
            rep = self.run_at("18:30")                                         # after the close
        self.assertEqual(self.alpaca.closed_all, 1)
        self.assertIn("open while the market is closed: TSLA", logs.output[0])
        self.assertTrue(rep.problems)

    def test_unknown_position_pings(self):
        self.alpaca.held["GME"] = 10
        with self.assertLogs("app.reconcile", level="ERROR"):
            rep = self.run_at("10:30")
        self.assertIn("GME: Alpaca holds 10 shares that aren't in today's books", rep.problems)

    def test_open_and_protected_mid_morning_is_just_noted(self):
        cid = self.placed("TSLA", status="filled")
        self.alpaca.orders[cid] = OrderInfo("BTSLA", cid, "filled", 6, 100.0)
        self.alpaca.held["TSLA"] = 6
        rep = self.run_at("10:30")
        self.assertEqual(rep.problems, [])
        self.assertIn("open and protected at Alpaca: TSLA 6", rep.notes)

    def test_nothing_going_on(self):
        self.assertFalse(self.run_at("08:00").anything)


if __name__ == "__main__":
    unittest.main()
