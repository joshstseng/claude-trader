import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from app import bumi_live as L
from app.research.data import D

NY = ZoneInfo("America/New_York")
S = L.load_settings()


class Broker:
    def __init__(self, held=None, equity=50000.0):
        self.held, self.eq, self.sent, self.orders = dict(held or {}), equity, [], {}

    def equity(self):
        return self.eq

    def positions(self):
        return dict(self.held)

    def order(self, cid):
        return self.orders.get(cid)

    def submit_opg(self, sym, side, qty, cid):
        self.sent.append((sym, side, qty, cid))
        self.orders[cid] = {"status": "filled", "filled_qty": qty, "filled_price": 100.0}
        return "accepted"


def plan(day="2026-11-20", actions=None, targets=None):
    actions = actions or {}
    rows = [{"sym": u, "etf": e, "action": actions.get(u, "none"), "why": "dip", "stop": None, "since": None}
            for u, e in S["universe"].items()]
    return {"as_of": day, "vix": 25.0, "vix_fresh": True, "calm": False, "rows": rows, "targets": targets or {}, "cash": 1.0}


PX = {"QLD": 100.0, "SSO": 100.0, "UWM": 50.0, "DDM": 80.0, "QQQ": 500.0}
AT_9 = datetime(2026, 11, 23, 9, 5, tzinfo=NY)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "state.json"
        self.state = L.State(self.file)


class Orders(Base):
    def test_mode_is_shadow_unless_exactly_paper(self):
        for v, want in ((None, "shadow"), ("", "shadow"), ("shadow", "shadow"), (" PAPER ", "paper")):
            env = {} if v is None else {"BUMI_MODE": v}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(L.mode(), want)

    def test_buy_size_and_sells_first(self):
        p = plan(actions={"QQQ": "buy", "SPY": "sell"}, targets={"QLD": .25})
        o, n = L.build_orders(p, S, 50000, {"SSO": 40}, PX, 0.0)
        self.assertEqual([(x.sym, x.side, x.qty) for x in o], [("SSO", "sell", 40), ("QLD", "buy", 124)])
        self.assertEqual(n, [])

    def test_core_trades_only_when_weight_changes(self):
        p = plan(targets={"QQQ": .5})
        self.assertEqual(L.build_orders(p, S, 50000, {"QQQ": 49}, PX, .5)[0], [])
        o = L.build_orders(p, S, 50000, {}, PX, 0.0)[0]
        self.assertEqual((o[0].sym, o[0].side, o[0].qty), ("QQQ", "buy", 49))
        o = L.build_orders(plan(), S, 50000, {"QQQ": 49}, PX, .5)[0]
        self.assertEqual((o[0].sym, o[0].side, o[0].qty), ("QQQ", "sell", 49))

    def test_never_sells_what_it_does_not_hold(self):
        o, n = L.build_orders(plan(actions={"QQQ": "sell"}), S, 50000, {}, PX, 0.0)
        self.assertEqual(o, [])
        self.assertIn("nothing is held", n[0])

    def test_missing_price_skips_order(self):
        o, n = L.build_orders(plan(actions={"QQQ": "buy"}), S, 50000, {}, {}, 0.0)
        self.assertEqual(o, [])
        self.assertIn("no price", n[0])


class Routine(Base):
    def paper(self, b=None):
        b = b or Broker()
        L.decide(plan(actions={"QQQ": "buy"}, targets={"QLD": .25}), S, self.state, PX, "paper", b)
        return b

    def test_decide_never_sends(self):
        self.assertEqual(self.paper().sent, [])

    def test_shadow_never_touches_broker(self):
        b = mock.Mock()
        L.decide(plan(actions={"QQQ": "buy"}, targets={"QLD": .25}), S, self.state, PX, "shadow", b)
        L.send("2026-11-20", AT_9, self.state, "shadow", b)
        self.assertEqual(b.mock_calls, [])
        self.assertEqual(self.state.doc["virtual"], {"QLD": 124})

    def test_a_shadow_plan_is_never_sent_after_switching_to_paper(self):
        L.decide(plan(actions={"QQQ": "buy"}, targets={"QLD": .25}), S, self.state, PX, "shadow")
        b = Broker()
        L.send("2026-11-20", AT_9, self.state, "paper", b)
        self.assertEqual(b.sent, [])

    def test_sends_once_even_after_restart(self):
        b = self.paper()
        L.send("2026-11-20", AT_9, self.state, "paper", b)
        L.send("2026-11-20", AT_9, L.State(self.file), "paper", b)
        self.assertEqual(len(b.sent), 1)
        self.assertEqual(b.sent[0][3], "bumi-20261120-QLD-buy")

    def test_crash_mid_send_does_not_duplicate(self):
        b = self.paper()
        b.orders["bumi-20261120-QLD-buy"] = {"status": "accepted", "filled_qty": 0, "filled_price": None}
        L.send("2026-11-20", AT_9, self.state, "paper", b)
        self.assertEqual(b.sent, [])

    def test_outside_window_sends_nothing(self):
        b = self.paper()
        for h, m in ((8, 59), (9, 28), (15, 0)):
            L.send("2026-11-20", datetime(2026, 11, 23, h, m, tzinfo=NY), self.state, "paper", b)
        self.assertEqual(b.sent, [])
        self.assertFalse(self.state.day("2026-11-20")["sent"])

    def test_old_plan_is_not_sent(self):
        b = self.paper()
        self.assertIn("no plan", L.send("2026-11-23", AT_9, self.state, "paper", b)[0])
        self.assertEqual(b.sent, [])

    def test_decide_twice_keeps_first_plan(self):
        b = self.paper()
        again = L.decide(plan(), S, self.state, PX, "paper", b)
        self.assertEqual(len(again["orders"]), 1)

    def test_confirm_reports_partial(self):
        b = self.paper()
        L.send("2026-11-20", AT_9, self.state, "paper", b)
        self.assertEqual(L.confirm("2026-11-20", self.state, b), [])
        b.orders["bumi-20261120-QLD-buy"] = {"status": "partially_filled", "filled_qty": 3, "filled_price": 100.0}
        self.assertIn("3/124", L.confirm("2026-11-20", self.state, b)[0])


class Align(unittest.TestCase):
    def bars(self, days):
        return [D(datetime(d.year, d.month, d.day, tzinfo=NY), 1, 1, 1, 1) for d in days]

    def test_requires_final_bar(self):
        a, b = date(2026, 11, 19), date(2026, 11, 20)
        with self.assertRaises(ValueError):
            L.align({"A": self.bars([a])}, {a: 20.0}, b, True)
        _, v, ok = L.align({"A": self.bars([a, b])}, {a: 21.0}, b, True)
        self.assertEqual((v, ok), ([21.0, 21.0], False))


if __name__ == "__main__":
    unittest.main()
