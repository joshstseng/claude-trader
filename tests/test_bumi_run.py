import asyncio
import tempfile
import unittest
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app import bumi_live as L, bumi_run as R
from app.market import Session
from tests.test_bumi import series
from tests.test_bumi_live import Broker

NY = ZoneInfo("America/New_York")
S = L.load_settings()
FRI, MON = date(2026, 11, 20), date(2026, 11, 23)


class Cal:
    def session(self, d):
        return Session(d, dtime(9, 30), dtime(16, 0)) if d.weekday() < 5 else None


def at(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=NY)


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = L.State(Path(self.tmp.name) / "s.json")
        self.posts, self.reports, self.fetches, self.pause = [], [], [], False
        self.fresh, self.fail = True, False
        self.broker = Broker()

    def fetch(self, day, now):
        self.fetches.append(day)
        if self.fail:
            raise ValueError("no bars")
        n = 400
        b = series(n=n, seed=3)
        out = [type(x)(datetime.combine(day - timedelta(days=n - 1 - i), dtime(0), tzinfo=NY), x.o, x.h, x.l, x.c) for i, x in enumerate(b)]
        return {u: out for u in S["universe"]}, [15.0] * n, self.fresh, {"QQQ": 500.0, "QLD": 100.0}, "note"

    def routine(self, mode="paper"):
        async def post(where, text, ping):
            self.posts.append((where, text, ping))
        return R.Routine(S, self.state, Cal(), self.broker, self.fetch, post,
                         lambda d, t: self.reports.append((d, t)), lambda: self.pause, mode)

    def tick(self, r, now):
        asyncio.run(r.tick(now))


class Schedule(Harness):
    def test_latest_done(self):
        c = Cal()
        self.assertEqual(R.latest_done(c, at(FRI, 16, 29)), date(2026, 11, 19))
        self.assertEqual(R.latest_done(c, at(FRI, 16, 30)), FRI)
        self.assertEqual(R.latest_done(c, at(date(2026, 11, 21), 12)), FRI)
        self.assertEqual(R.latest_done(c, at(MON, 9, 5)), FRI)

    def test_weekend_start_catches_up_once(self):
        r = self.routine()
        for m in (0, 1):
            self.tick(r, at(date(2026, 11, 21), 12, m))
        self.assertEqual(self.fetches, [FRI])
        self.assertEqual(sum(p[0] == "setups" for p in self.posts), 1)

    def test_waits_for_fresh_vix_then_decides_without_buys(self):
        self.fresh = False
        r = self.routine()
        self.tick(r, at(FRI, 16, 30))
        self.assertIsNone(self.state.day(FRI.isoformat()))
        self.tick(r, at(FRI, 19, 0))
        self.assertFalse(self.state.day(FRI.isoformat())["plan"]["vix_fresh"])

    def test_no_data_means_no_plan_and_one_ping(self):
        self.fail = True
        r = self.routine()
        self.tick(r, at(FRI, 19, 0))
        self.tick(r, at(FRI, 19, 10))
        self.assertIsNone(self.state.day(FRI.isoformat()))
        self.assertEqual([p[2] for p in self.posts], [True])

    def test_report_in_before_decision(self):
        r = self.routine()
        self.tick(r, at(FRI, 16, 15))
        self.assertEqual([d for d, _ in self.reports], [FRI.isoformat()])
        self.assertEqual(self.fetches, [date(2026, 11, 19)])


class Orders(Harness):
    def seed(self, mode="paper"):
        plan = {"as_of": FRI.isoformat(), "vix": 25.0, "vix_fresh": True, "calm": False, "targets": {"QLD": .25}, "cash": .75,
                "rows": [{"sym": u, "etf": e, "action": "buy" if u == "QQQ" else "none", "why": "dip", "stop": None, "since": None}
                         for u, e in S["universe"].items()]}
        L.decide(plan, S, self.state, {"QLD": 100.0}, mode, self.broker if mode == "paper" else None)

    def test_sends_in_window_then_confirms(self):
        self.seed()
        r = self.routine()
        self.tick(r, at(MON, 8, 59))
        self.assertEqual(self.broker.sent, [])
        self.tick(r, at(MON, 9, 0))
        self.tick(r, at(MON, 9, 1))
        self.assertEqual(len(self.broker.sent), 1)
        self.tick(r, at(MON, 9, 35))
        self.tick(r, at(MON, 9, 36))
        self.assertEqual(sum("filled" in p[1] for p in self.posts), 1)

    def test_global_pause_blocks_send(self):
        self.seed()
        self.pause = True
        r = self.routine()
        self.tick(r, at(MON, 9, 5))
        self.tick(r, at(MON, 9, 6))
        self.assertEqual(self.broker.sent, [])
        self.assertEqual(sum("paused" in p[1] for p in self.posts), 1)

    def test_flatten_cancels_unsent_plan(self):
        self.seed()
        self.broker.close_all = lambda: self.broker.held.clear()
        self.broker.held = {"QQQ": 10}
        self.assertIn("closing 1", L.flatten(self.state, "paper", self.broker))
        self.tick(self.routine(), at(MON, 9, 5))
        self.assertEqual(self.broker.sent, [])
        self.assertEqual(self.broker.held, {})

    def test_shadow_routine_never_orders(self):
        self.seed("shadow")
        self.tick(self.routine("shadow"), at(MON, 9, 5))
        self.assertEqual(self.broker.sent, [])


if __name__ == "__main__":
    unittest.main()
