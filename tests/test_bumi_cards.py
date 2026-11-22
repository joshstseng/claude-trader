import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import discord

from app import bumi_cards as C, bumi_live as L, head, tradelog
from tests.test_bumi_live import AT_9, Broker, PX, plan

S = L.load_settings()


class Msg:
    def __init__(self, ch, i):
        self.ch, self.id = ch, i

    async def edit(self, embed=None):
        if self.id not in self.ch.msgs:
            raise discord.NotFound(SimpleNamespace(status=404, reason="gone"), "gone")
        self.ch.msgs[self.id] = embed.description

    async def delete(self):
        if self.id not in self.ch.msgs:
            raise discord.NotFound(SimpleNamespace(status=404, reason="gone"), "gone")
        del self.ch.msgs[self.id]


class Chan:
    def __init__(self):
        self.msgs, self.n = {}, 100

    async def send(self, embed=None, silent=False):
        self.n += 1
        self.msgs[self.n] = embed.description
        return Msg(self, self.n)

    def get_partial_message(self, i):
        return Msg(self, i)


class CardBroker(Broker):
    def __init__(self):
        super().__init__()
        self.prices, self.sell = {}, None

    def position_details(self):
        return {k: {"qty": v, "price": self.prices.get(k, 110.0)} for k, v in self.held.items()}

    def last_sell(self, sym, since):
        return self.sell


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "s.json"
        self.state = L.State(self.file)
        self.b = CardBroker()
        self.live, self.closed = Chan(), Chan()
        self.cards = C.BumiCards(self.state, self.b, {1: self.live, 2: self.closed}.get, 1, 2)

    def sync(self, day="2026-11-24"):
        asyncio.run(self.cards.sync(day))

    def open_qld(self):
        L.book_fill(self.state, "QLD", "buy", 100, 100.0, "2026-11-23", "RSI(2) 5.0, VIX 25.0", S)
        self.b.held["QLD"] = 100


class Ledger(Base):
    def test_confirm_books_real_fills_once(self):
        L.decide(plan(actions={"QQQ": "buy"}, targets={"QLD": .25}), S, self.state, PX, "paper", self.b)
        L.send("2026-11-20", AT_9, self.state, "paper", self.b)
        L.confirm("2026-11-20", self.state, self.b, "2026-11-23", S)
        L.confirm("2026-11-20", self.state, self.b, "2026-11-23", S)
        lot = self.state.ledger["open"]["QLD"]
        self.assertEqual((lot["qty"], lot["entry"], lot["day_in"], lot["kind"]), (124, 100.0, "2026-11-23", "dip"))
        self.assertEqual(len(self.state.ledger["fills"]), 1)

    def test_sell_realizes_pnl_and_partial_keeps_card(self):
        L.book_fill(self.state, "QQQ", "buy", 10, 100.0, "2026-11-23", "core", S)
        L.book_fill(self.state, "QQQ", "buy", 10, 120.0, "2026-11-24", "core", S)
        self.state.ledger["open"]["QQQ"]["card"] = "7"
        t = L.book_fill(self.state, "QQQ", "sell", 5, 130.0, "2026-11-25", "core to 25%", S)
        self.assertEqual((t["pnl"], t["live_card"]), (100.0, None))
        t = L.book_fill(self.state, "QQQ", "sell", 15, 100.0, "2026-11-26", "core to 0%", S)
        self.assertEqual((t["pnl"], t["live_card"]), (-150.0, "7"))
        self.assertEqual(self.state.ledger["open"], {})

    def test_reconcile_books_a_flatten(self):
        self.open_qld()
        self.b.held = {}
        self.b.sell = {"price": 90.0, "qty": 100, "day": "2026-11-24"}
        self.assertEqual(L.reconcile(self.state, self.b, S, "2026-11-24"), [])
        self.assertEqual(self.state.ledger["closed"][0]["pnl"], -1000.0)

    def test_reconcile_warns_once(self):
        self.open_qld()
        self.b.held = {"QLD": 50, "AAPL": 1}
        self.assertEqual(len(L.reconcile(self.state, self.b, S, "2026-11-24")), 2)
        self.assertEqual(L.reconcile(self.state, self.b, S, "2026-11-24"), [])

    def test_old_state_file_gets_a_ledger(self):
        self.file.write_text(json.dumps({"core": 0.0, "virtual": {}, "days": {}}))
        self.assertEqual(L.State(self.file).ledger["open"], {})

    def test_numbers(self):
        self.open_qld()
        L.book_fill(self.state, "QLD", "sell", 100, 105.0, "2026-11-24", "stop", S)
        n = L.numbers(self.state)
        self.assertEqual((n["all_time"], n["all_trades"], n["open"]), (500.0, 1, 0))
        self.assertEqual(n["days"]["2026-11-24"]["wins"], 1)


class Cards(Base):
    def test_one_card_refreshed_then_moved_to_closed(self):
        self.open_qld()
        self.sync()
        self.assertEqual(len(self.live.msgs), 1)
        self.assertIn("+$1,000.00", list(self.live.msgs.values())[0])
        self.b.prices["QLD"] = 95.0
        self.sync()
        self.assertEqual(len(self.live.msgs), 1)
        self.assertIn("−$500.00", list(self.live.msgs.values())[0])
        L.book_fill(self.state, "QLD", "sell", 100, 95.0, "2026-11-25", "QQQ stop or time exit", S)
        self.b.held = {}
        self.sync()
        self.sync()
        self.assertEqual(self.live.msgs, {})
        self.assertEqual(len(self.closed.msgs), 1)
        self.assertIn("held 2 days", list(self.closed.msgs.values())[0])

    def test_restart_reuses_card_and_deleted_card_comes_back(self):
        self.open_qld()
        self.sync()
        self.cards.state = L.State(self.file)
        self.sync()
        self.assertEqual(len(self.live.msgs), 1)
        self.live.msgs.clear()
        self.sync()
        self.assertEqual(len(self.live.msgs), 1)

    def test_core_card_text(self):
        lot = {"sym": "QQQ", "qty": 10, "entry": 100.0, "day_in": "2026-11-23", "kind": "core", "under": None}
        self.assertIn("No stop", C.live_text(lot, 101.0, None, "2026-11-23")[0])


class Uri(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = tradelog.TradeLog(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.log.close)

    def test_numbers_and_summary(self):
        day = "2026-11-24"
        self.log.set_fleet("numbers:bumi", json.dumps({"days": {day: {"orders": 2, "filled": 2, "closed": 1, "wins": 1,
                           "day_pnl": 500.0}}, "all_time": 700.0, "all_trades": 3, "open": 1, "at_risk": 250.0}))
        n = head.bot_numbers(self.log, "bumi", day)
        self.assertEqual((n["day_pnl"], n["all_time"], n["open"], n["at_risk"]), (500.0, 700.0, 1, 250.0))
        text = head.summary_text([n], day, False)
        self.assertIn("held overnight", text)
        self.assertNotIn("still open", text)

    def test_no_or_bad_numbers_are_zero(self):
        self.assertEqual(head.bot_numbers(self.log, "bumi", "2026-11-24")["all_time"], 0.0)
        self.log.set_fleet("numbers:bumi", "not json")
        self.assertEqual(head.bot_numbers(self.log, "bumi", "2026-11-24")["open"], 0)


if __name__ == "__main__":
    unittest.main()
