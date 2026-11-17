"""Backtest runs: --set overrides, metrics, and the report."""

import unittest
from collections import Counter

from app import settings, strategies
from app.backtest import report
from app.backtest.run import apply_overrides
from app.backtest.signals import BtSignal


def trade(day, r, usd, result="flat", mfe=0.5, risk=1.0, entry=100.0, t="10:00"):
    return BtSignal(day=day, symbol="X", status="pass", trigger_time=t, entry=entry, risk_per_share=risk,
                    outcome={"result": result, "r_net": r, "r_gross": r + 0.05, "pnl_usd": usd, "mfe_r": mfe})


class OverridesTest(unittest.TestCase):
    def setUp(self):
        self.s, self.r = strategies.load("orb").settings, settings.risk_rules()

    def test_strategy_risk_and_selection_settings(self):
        s, r, sel = apply_overrides(self.s, self.r, ["exit.target=1R", "min_volume_x=1.5",
                                                     "risk.max_trades_per_day=2", "selection.cash_limit=false"])
        self.assertEqual((s["exit"]["target"], s["min_volume_x"]), ("1R", 1.5))
        self.assertEqual(r["max_trades_per_day"], 2)
        self.assertIs(sel["cash_limit"], False)
        self.assertEqual(self.s["exit"]["target"], "2R")           # the saved settings aren't touched

    def test_defaults_to_cash_limit_on(self):
        self.assertIs(apply_overrides(self.s, self.r, [])[2]["cash_limit"], True)

    def test_typos_are_caught(self):
        for bad in ["exit.targt=1R", "risk.max_trades=2", "nonsense"]:
            with self.assertRaises(ValueError):
                apply_overrides(self.s, self.r, [bad])


class MetricsTest(unittest.TestCase):
    def test_numbers(self):
        t = [trade("2026-01-05", 2.0, 100, "target", mfe=2.0), trade("2026-01-05", -1.0, -50, "stop"),
             trade("2026-01-06", -1.0, -50, "stop"), trade("2026-01-07", 0.5, 25)]
        m = report.metrics(t)
        self.assertEqual((m["trades"], m["days"], m["target"], m["stop"], m["flat"]), (4, 3, 1, 2, 1))
        self.assertEqual(m["win_rate"], 0.5)
        self.assertEqual(m["avg_r"], 0.125)
        self.assertEqual(m["total_usd"], 25)
        self.assertEqual(m["profit_factor"], 125 / 100)
        self.assertEqual(m["max_dd_usd"], -50)                     # +50 on day 1, then -50 on day 2
        self.assertEqual(m["worst_losing_streak"], 2)
        self.assertEqual(m["reached_2r"], 0.25)

    def test_report_renders(self):
        t = [trade("2026-01-05", 2.0, 100, "target"), trade("2026-02-05", -1.0, -50, "stop", risk=0.2)]
        m = report.metrics(t)
        md = report.render(run_id=2, label="1R target", settings_line="x", code="abc", views={"As traded": m},
                           traded=t, every=t, why_not=Counter({"not alerted: daily alert cap (5)": 3}),
                           baseline=(1, "baseline", {**m, "avg_r": 0.0}))
        self.assertIn("# ORB backtest run #2: 1R target", md)
        self.assertIn("this has an edge", md)
        self.assertIn("## Compared with baseline run #1 (baseline)", md)
        self.assertIn("| Avg per trade | +0.000R | +0.500R | **+0.500R** |", md)
        self.assertIn("| 2026-02 | 1 | −1.000R | −$50 |", md)
        self.assertIn("Blind spots", md)


if __name__ == "__main__":
    unittest.main()
