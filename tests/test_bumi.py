import random
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.research.data import D
from app.research.experiments.longmkt import wants
from app.settings import _read_json
from app import paths, vix as V
from app.strategies import BRAINS, bumi
from types import SimpleNamespace

S = _read_json(paths.STRATEGY_CONFIG_DIR / "bumi.json")
NY = ZoneInfo("America/New_York")


def series(n=900, seed=1, drift=.0006, sd=.012):
    r = random.Random(seed)
    p, out, t = 100.0, [], datetime(2020, 1, 1, tzinfo=NY)
    for i in range(n):
        o = p * (1 + r.gauss(0, sd / 3))
        c = o * (1 + r.gauss(drift, sd))
        h, l = max(o, c) * (1 + abs(r.gauss(0, sd / 2))), min(o, c) * (1 - abs(r.gauss(0, sd / 2)))
        out.append(D(t + timedelta(days=i), o, h, l, c))
        p = c
    return out


class Rules(unittest.TestCase):
    def test_matches_research_rules(self):
        for seed in range(8):
            b = series(seed=seed)
            r = random.Random(seed + 50)
            v = [r.uniform(12, 32) for _ in b]
            m = SimpleNamespace(bars={"X": b}, c={"X": [x.c for x in b]}, vix=v)
            old = wants(m, "X", vt=20, trail=1.5)
            self.assertEqual(bumi.track(b, v, S).want[:-1], old[:-1])

    def test_no_signal_when_vix_low(self):
        b = series()
        self.assertFalse(any(bumi.track(b, [15.0] * len(b), S).want))

    def test_weights_core_and_room(self):
        all_on = dict.fromkeys(S["universe"], True)
        none = dict.fromkeys(S["universe"], False)
        self.assertEqual(bumi.weights(none, True, S), {"QQQ": .5})
        self.assertEqual(bumi.weights(none, False, S), {})
        self.assertNotIn("QQQ", bumi.weights(all_on, True, S))
        three = dict(all_on, DIA=False)
        self.assertAlmostEqual(bumi.weights(three, True, S)["QQQ"], .25)

    def test_stale_vix_blocks_new_buy_only(self):
        for seed in range(30):
            b = series(n=500, seed=seed)
            v = [25.0] * len(b)
            t = bumi.track(b, v, S)
            if t.want[-1] and not t.want[-2]:
                bars = {u: b for u in S["universe"]}
                self.assertEqual(bumi.plan_next(bars, v, S)["rows"][0]["action"], "buy")
                p = bumi.plan_next(bars, v, S, vix_fresh=False)
                self.assertEqual(p["rows"][0]["action"], "none")
                self.assertEqual(p["targets"], {})
                return
        self.fail("no new-signal case found")

    def test_stays_out_of_the_day_trading_brains(self):
        self.assertNotIn("bumi", BRAINS)


class Vix(unittest.TestCase):
    D0, D1 = date(2026, 11, 19), date(2026, 11, 20)

    def test_parse_cboe(self):
        got = V.parse_cboe("DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2026,20,22,19,21.5\n11/19/2026,x,x,x,bad\n11/18/2026,1,1,1,1\n")
        self.assertEqual(got, {self.D1: 21.5})

    def test_uses_backup_when_primary_stale(self):
        d = V.fetch(self.D1, cboe=lambda: {self.D0: 18.0}, yahoo=lambda: {self.D1: 19.0})
        self.assertTrue(d.fresh)
        self.assertEqual((d.source, d.series[self.D0], d.series[self.D1]), ("yahoo", 18.0, 19.0))

    def test_stale_when_all_old_or_failed(self):
        def boom():
            raise OSError("down")
        d = V.fetch(self.D1, cboe=boom, yahoo=lambda: {self.D0: 18.0})
        self.assertFalse(d.fresh)
        self.assertEqual(d.source, "yahoo")
        self.assertFalse(V.fetch(self.D1, cboe=boom, yahoo=boom).fresh)


if __name__ == "__main__":
    unittest.main()
