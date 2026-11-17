"""Selection: alert cap first come first served, then the risk check's daily rules."""

import unittest

from app import settings, strategies
from app.backtest.select import Rules, select
from app.backtest.signals import BtSignal


def sig(sym, t, *, day="2026-10-19", status="pass", max_loss=40.0, cost=3000.0, exit_time="15:55"):
    return BtSignal(day=day, symbol=sym, status=status, trigger_time=t, max_loss=max_loss, cost=cost,
                    reason="" if status == "pass" else "budget: too expensive",
                    outcome={"exit_time": exit_time, "r_net": 0.0, "pnl_usd": 0.0, "result": "flat"})


def whys(decisions):
    return [(d.signal.symbol, d.why) for d in decisions]


class SelectTest(unittest.TestCase):
    def test_live_settings(self):
        r = Rules.from_settings(strategies.load("orb").settings, settings.risk_rules(), cash_limit=True)
        self.assertEqual((r.alert_cap, r.max_trades, r.max_daily_loss, r.cash_available), (5, 3, 150.0, 4500.0))

    def test_first_come_first_served_cap_then_max_trades(self):
        day = [sig(s, "09:50") for s in "ABCDEFG"]
        out = select(day, Rules(alert_cap=5, max_trades=3, max_daily_loss=0))
        self.assertEqual(whys(out), [
            ("A", "taken"), ("B", "taken"), ("C", "taken"),
            ("D", "risk: max 3 trades a day"), ("E", "risk: max 3 trades a day"),
            ("F", "not alerted: daily alert cap (5)"), ("G", "not alerted: daily alert cap (5)")])
        self.assertEqual([d.alerted for d in out], [True] * 5 + [False] * 2)

    def test_refused_signals_dont_use_an_alert(self):
        day = [sig("A", "09:50", status="refused"), sig("B", "09:55")]
        out = select(day, Rules(alert_cap=1, max_trades=0, max_daily_loss=0))
        self.assertEqual(whys(out), [("A", "refused (budget)"), ("B", "taken")])

    def test_daily_loss_counts_max_losses_at_the_stops(self):
        day = [sig("A", "09:50", max_loss=50), sig("B", "09:55", max_loss=50),
               sig("C", "10:00", max_loss=60), sig("D", "10:05", max_loss=45)]
        out = select(day, Rules(alert_cap=0, max_trades=0, max_daily_loss=150))
        self.assertEqual(whys(out), [("A", "taken"), ("B", "taken"),
                                     ("C", "risk: daily loss limit ($150)"), ("D", "taken")])

    def test_cash_is_freed_when_a_position_exits(self):
        day = [sig("A", "09:50", cost=3500, exit_time="10:20"),      # stopped out at 10:20
               sig("B", "10:00", cost=3500),                         # A still open: no cash
               sig("C", "10:30", cost=3500)]                         # A has exited: cash again
        out = select(day, Rules(alert_cap=0, max_trades=0, max_daily_loss=0, cash_limit=True,
                                cash_available=4500))
        self.assertEqual(whys(out), [("A", "taken"), ("B", "risk: not enough cash (positions still open)"),
                                     ("C", "taken")])

    def test_each_day_starts_fresh(self):
        days = [sig("A", "09:50", day="2026-10-19"), sig("B", "09:55", day="2026-10-19"),
                sig("C", "09:50", day="2026-10-20")]
        out = select(days, Rules(alert_cap=1, max_trades=0, max_daily_loss=0))
        self.assertEqual([d.taken for d in out], [True, False, True])


if __name__ == "__main__":
    unittest.main()
