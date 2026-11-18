"""Step 1b.8: real paper trades vs the backtest's version of the same trades."""

import tempfile
import unittest
from pathlib import Path

from app import costs, tradelog


class CostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = tradelog.TradeLog(Path(self.tmp.name) / "t.db")
        self.run = self.log.start_run("orb", "live", {}, date_from="2026-11-18", date_to="2026-11-19")

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def trade(self, day, sym, entry, stop, target, bt, order):
        """bt = (result, exit, r_gross) from the 4:15 outcome engine; order = the orders row's fields."""
        self.log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop, target,"
                            " trigger_time, qty, created_at) VALUES (?, 'orb', 'live', ?, ?, 'pass', ?, ?, ?, '10:35',"
                            " 6, 'x')", (self.run, day, sym, entry, stop, target))
        sid = self.log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
        self.log.db.execute("INSERT INTO outcomes (signal_id, result, exit_price, r_multiple, r_gross, method,"
                            " resolved_at) VALUES (?, ?, ?, 0, ?, 'test', 'x')", (sid, *bt))
        cid = f"orb-{day}-{sid}"
        self.log.add_order(sid, cid, sym, 6, round(entry + 0.37, 2), stop, target)
        self.log.update_order(cid, **order)

    def setup_two_days(self):
        # Nov 18 TSLA: plan 365.75 / 358.32 (risk 7.43). Backtest: flat at 367.24.
        # Real: filled 365.90 (+0.15), sold flat at 367.10 -> +1.20/sh, 6 sh = +7.20
        self.trade("2026-11-18", "TSLA", 365.75, 358.32, 380.61, ("flat", 367.24, 0.2005),
                   dict(status="closed", filled_qty=6, filled_price=365.90, entry_slippage=0.15,
                        exit_reason="flat", exit_price=367.10, pnl_usd=7.20))
        # Nov 18 AMD: the limit never filled; the backtest says it hit its target
        self.trade("2026-11-18", "AMD", 150.00, 148.00, 154.00, ("target", 154.00, 2.0),
                   dict(status="cancelled", filled_qty=0))
        # Nov 19 NVDA: stopped out, 2 cents of stop slippage: -20.40
        self.trade("2026-11-19", "NVDA", 180.00, 177.00, 186.00, ("stop", 177.00, -1.0),
                   dict(status="closed", filled_qty=6, filled_price=180.40, entry_slippage=0.40, exit_reason="stop",
                        exit_price=176.98, exit_slippage=-0.02, pnl_usd=-20.52))

    def test_cost_is_measured_against_the_backtests_own_result(self):
        self.setup_two_days()
        t = next(x for x in costs.paper_trades(self.log, "2026-11-18") if x["symbol"] == "TSLA")
        self.assertAlmostEqual(t["cost_ps"], 0.29)                          # 1.49 backtest - 1.20 real
        self.assertAlmostEqual(t["cost_pct_side"] * 100, 0.29 / (365.90 + 367.10) * 100)   # ~0.040%
        self.assertAlmostEqual(t["cost_r"], 0.29 / 7.43)

    def test_measured_fill_rate_and_missed_trades(self):
        self.setup_two_days()
        m = costs.measured(costs.paper_trades(self.log, "2026-11-18"))
        self.assertEqual((m["orders"], m["filled"], m["closed"], m["missed"]), (2, 1, 1, 1))
        self.assertEqual(m["missed_bt_r"], 2.0)                             # we missed a winner

    def test_daily_section(self):
        self.setup_two_days()
        text = costs.day_section(self.log, "2026-11-18", 0.0003)
        self.assertIn("➖ **TSLA** 6 sh: in $365.90 → out $367.10 (flat) · **+$7.20** +0.16R · "
                      "backtest said ➖ +0.20R", text)
        self.assertIn("⌛ **AMD**: limit never filled (backtest: ✅ +2.00R)", text)
        self.assertIn("Today **+$7.20** · all-time paper P&L **−$13.32** over 2 trades (1 winner)", text)
        self.assertIn("💸 Costs: fill rate 1/2 · entry slippage +$0.15/sh", text)
        self.assertIn("real cost vs backtest: 0.040%/side", text)
        self.assertIn("missed entries would have averaged +2.00R", text)

    def test_quiet_day_has_no_section(self):
        self.assertIsNone(costs.day_section(self.log, "2026-11-18", 0.0003))

    def test_pnl_command(self):
        self.setup_two_days()
        text = costs.pnl_text(self.log, 0.0003)
        self.assertTrue(text.startswith("**ORB paper trading, all time:** 2 closed trades · 1 winner · **−$13.32**"))
        self.assertIn("`Wed Nov 18` +$7.20", text)
        self.assertIn("`Thu Nov 19` −$20.52", text)
        self.assertIn("2 of ~20 trades needed", text)

    def test_pnl_before_any_trade(self):
        self.assertEqual(costs.pnl_text(self.log, 0.0003), "No paper trades yet. Approve an alert to place one.")


if __name__ == "__main__":
    unittest.main()
