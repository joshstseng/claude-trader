"""Step 1b.6: out by the close. A fake Alpaca stands in for the real one."""

import asyncio
import tempfile
import unittest
from datetime import date, datetime, time as dtime
from pathlib import Path

from app import settings, strategies, tradelog
from app.account import DayAccount
from app.broker import OrderInfo
from app.flatten import Flattener
from app.market import NY, Session

DAY = "2026-10-19"


class FakeAlpaca:
    def __init__(self):
        self.positions_held = {}         # symbol -> qty
        self.closed_at = {}              # symbol -> fill price when we sell
        self.legs = {}                   # client id -> ("stop" | "target", price, when)
        self.orders_open = []
        self.leave_open = set()          # symbols that refuse to close (for the backup test)
        self.close_calls = 0

    def close_all(self):
        self.close_calls += 1
        out = []
        for sym in list(self.positions_held):
            if sym in self.leave_open:
                continue
            out.append((sym, f"close-{sym}"))
            del self.positions_held[sym]
        self.orders_open = []
        return out

    def fill_of(self, oid):
        return "filled", self.closed_at[oid.split("-", 1)[1]]

    def exit_fill(self, cid):
        return self.legs.get(cid)

    def positions(self):
        return [{"symbol": s, "qty": q, "avg_entry": 0, "price": None, "unrealized": 0}
                for s, q in self.positions_held.items()]

    def open_orders(self):
        return self.orders_open


class FlattenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rules = settings.risk_rules()
        self.log = tradelog.TradeLog(self.root / "t.db")
        self.run = self.log.start_run("orb", "live", {}, date_from=DAY, date_to=DAY)
        self.acct = DayAccount.for_day(self.root, DAY, self.rules)
        self.alpaca = FakeAlpaca()

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def trade(self, sym, qty, price, max_loss=40.0):
        """A placed order: a signal row, an orders row, and the account entry."""
        self.log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop,"
                            " target, qty, created_at) VALUES (?, 'orb', 'live', ?, ?, 'pass', ?, ?, ?, ?, 'x')",
                            (self.run, DAY, sym, price, price - 2, price + 4, qty))
        sid = self.log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
        self.log.add_order(sid, f"orb-{DAY}-{sid}", sym, qty, price, price - 2, price + 4)
        self.acct.record_entry(sym, qty, price, max_loss, signal_id=sid)
        return f"orb-{DAY}-{sid}"

    def flattener(self):
        return Flattener(self.alpaca, self.log, self.rules, runs_root=self.root, fill_wait_s=0.5)

    def test_open_position_is_sold_and_booked(self):
        cid = self.trade("TSLA", 6, 365.75)
        self.alpaca.positions_held["TSLA"] = 6
        self.alpaca.closed_at["TSLA"] = 367.24
        rep = self.flattener().flatten(DAY)
        self.assertEqual(rep.exits, [("TSLA", 6, "flat", 367.24, 8.94)])
        self.assertEqual(rep.still_open, [])
        a = DayAccount.for_day(self.root, DAY, self.rules)
        self.assertEqual((a.open_positions, a.realized_pnl, a.cash), ([], 8.94, 5000.0))
        row = self.log.db.execute("SELECT * FROM orders WHERE client_order_id = ?", (cid,)).fetchone()
        self.assertEqual((row["status"], row["exit_reason"], row["exit_price"], row["pnl_usd"]),
                         ("closed", "flat", 367.24, 8.94))
        self.assertIn("➖ TSLA: 6 sh, flat at $367.24 (+$8.94)", rep.text())
        sid = self.log.order_for_signal(1)["signal_id"]
        self.assertEqual(rep.alert_updates, [(sid, "➖ [ORB] TSLA · sold at the close at $367.24 · +$8.94", "done")])

    def test_a_trade_stopped_out_earlier_is_booked_from_its_legs(self):
        cid = self.trade("NVDA", 10, 180.0)
        self.alpaca.legs[cid] = ("stop", 177.9, "2026-10-19T11:02:00-04:00")
        rep = self.flattener().flatten(DAY)
        self.assertEqual(rep.exits, [("NVDA", 10, "stop", 177.9, -21.0)])
        self.assertIn("❌ NVDA", rep.text())

    def test_an_unfilled_entry_is_cancelled_and_uncounted(self):
        self.trade("AMD", 20, 150.0)                               # no position, no legs: never filled
        rep = self.flattener().flatten(DAY)
        self.assertEqual(rep.cancelled_entries, ["AMD"])
        self.assertEqual(DayAccount.for_day(self.root, DAY, self.rules).entries_today, 0)

    def test_something_left_open_pings_you(self):
        self.trade("TSLA", 6, 365.75)
        self.alpaca.positions_held["TSLA"] = 6
        self.alpaca.leave_open.add("TSLA")
        with self.assertLogs("app.flatten", level="ERROR") as logs:
            rep = self.flattener().flatten(DAY, phase="backup")
        self.assertEqual(rep.still_open, ["TSLA"])
        self.assertIn("still open after flattening: TSLA", logs.output[0])
        self.assertIn("⚠️ **Still open:** TSLA", rep.text())

    def test_kill_switch_wording(self):
        self.trade("TSLA", 6, 365.75)
        self.alpaca.positions_held["TSLA"] = 6
        self.alpaca.closed_at["TSLA"] = 366.0
        rep = self.flattener().flatten(DAY, phase="kill switch")
        self.assertEqual(rep.exits[0][2], "flatten")
        self.assertTrue(rep.text().startswith("🛑 **[ORB] Flattened by /flatten**"))

    def test_nothing_open_reports_nothing(self):
        self.assertFalse(self.flattener().flatten(DAY).anything)


class FlattenScheduleTest(unittest.TestCase):
    def times(self, session):
        from app.routine import LogAlerter, OrbDay
        from app.scheduler import SimClock, run_day
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            bot = OrbDay(strategies.load("orb"), settings.risk_rules(), log, source="replay",
                         day=session.day.isoformat(), alerter=LogAlerter(), runs_root=Path(d) / "runs")
            clock = SimClock(datetime.combine(session.day, dtime(12, 0), tzinfo=NY))   # after the window
            calls = []

            async def flatten(b, phase):
                calls.append((phase, clock.now().strftime("%H:%M")))
            asyncio.run(run_day(bot, session, clock, simulated=True, flatten=flatten))
            log.close()
        return calls

    def test_355_then_backup_at_358(self):
        self.assertEqual(self.times(Session(date(2026, 10, 19), dtime(9, 30), dtime(16, 0))),
                         [("flat", "15:55"), ("backup", "15:58")])

    def test_early_close_day(self):
        self.assertEqual(self.times(Session(date(2026, 11, 27), dtime(9, 30), dtime(13, 0))),
                         [("flat", "12:55"), ("backup", "12:58")])


if __name__ == "__main__":
    unittest.main()
