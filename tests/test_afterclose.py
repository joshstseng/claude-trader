"""After the close: results for every signal of the day, and the #daily-summary text."""

import json
import tempfile
import unittest
from datetime import date, time as dtime
from pathlib import Path

from app import afterclose, market, outcomes, settings, tradelog
from app.routine import DayData, LogAlerter, OrbDay
from app import strategies
from tests.test_routine import TM_DIR, WALL

FIX = Path(__file__).parent / "fixtures"
TSLA_BARS = outcomes.bars_from_rows(json.loads((FIX / "alpaca-TSLA-2026-10-19-5m.json").read_text())["bars"])


def fake_fetch(symbols, day):
    """Alpaca stand-in: TSLA's real day; other stocks get no bars (-> no_data)."""
    return {"TSLA": TSLA_BARS} if "TSLA" in symbols else {}


class AfterCloseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        entry_dir = market.split_bundle(WALL, root / "bars")
        self.log = tradelog.TradeLog(root / "t.db")
        self.bot = OrbDay(strategies.load("orb"), settings.risk_rules(), self.log, source="live",
                          day="2026-10-19", alerter=LogAlerter(), runs_root=root / "runs",
                          day_data=DayData(bars=WALL, entry_dir=entry_dir, timemachine_dir=TM_DIR))
        self.bot.premarket(["CDNS", "TSLA"])
        for t in ("09:51", "10:36"):
            self.bot.tick(f"2026-10-19 {t}")
        tsla = next(r for r in self.log.signals(run_id=self.bot.run_id) if r["symbol"] == "TSLA")
        self.log.record_response(tsla["id"], "took")

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def resolve(self):
        return afterclose.resolve_day(self.log, "2026-10-19", fetch=fake_fetch, flat_by=dtime(15, 55),
                                      cost_pct=0.0003, run_id=self.bot.run_id)

    def test_every_signal_gets_a_result_once(self):
        self.assertEqual(self.resolve(), 2)
        self.assertEqual(self.resolve(), 0)                       # already done: nothing new
        rows = {r["symbol"]: r for r in self.log.signals(run_id=self.bot.run_id)}
        tsla = self.log.outcome(rows["TSLA"]["id"])
        self.assertEqual((tsla["result"], tsla["exit_time"], tsla["r_multiple"]), ("flat", "15:55", 0.171))
        self.assertEqual(self.log.outcome(rows["CDNS"]["id"])["result"], "no_data")

    def test_summary(self):
        self.resolve()
        text = afterclose.summary_text(self.log, "2026-10-19", run_id=self.bot.run_id)
        lines = text.splitlines()
        self.assertEqual(lines[0], "**Mon Oct 19** · 2 signals · 2 alerted · you took 1")
        self.assertIn("**Alerted (2):** 1 ➖ · 1 ❔ → **+0.17R** (avg +0.09R) · +$7.62", text)
        self.assertIn("**Your picks (1):** 1 ➖ → **+0.17R** · +$7.62", text)
        self.assertIn("`10:35` **TSLA** ➖ flat +0.17R · you: took it", text)
        self.assertIn("`09:50` **CDNS** ❔ no data", text)
        self.assertIn("no orders were placed", text)
        self.assertLess(len(text), 2000)

    def test_quiet_days(self):
        self.assertIn("no signals today", afterclose.summary_text(self.log, "2026-10-20"))
        self.assertIn("no checks ran today", afterclose.summary_text(self.log, "2026-10-20", scanned=False))

    def test_data_check_against_full_market_bars(self):
        """Live (Yahoo) said TSLA at 10:35; Alpaca's full-market bars don't confirm it (thin volume)."""
        orb = strategies.load("orb")
        c = afterclose.data_check(self.log, "2026-10-19", ["TSLA", "CDNS"], fetch=fake_fetch,
                                  session=market.SkillCalendar().session(date(2026, 10, 19)),
                                  settings=orb.settings, rules=settings.risk_rules(), cost_pct=0.0003,
                                  run_id=self.bot.run_id)
        self.assertEqual((c["live"], c["confirmed"]), (2, []))
        self.assertEqual(c["live_only"], [("CDNS", "09:50"), ("TSLA", "10:35")])   # CDNS: no bars in the fake
        line = afterclose.data_check_line(c)
        self.assertTrue(line.startswith("🔎 **Data check** (live Yahoo vs full-market data): 0 of 2 live signals confirmed"))
        self.assertIn("not in full-market data: CDNS, TSLA", line)

    def test_extra_line_shows_even_on_a_quiet_day(self):
        text = afterclose.summary_text(self.log, "2026-10-20", extra="🔎 Data check: x")
        self.assertTrue(text.endswith("🔎 Data check: x"))

    def test_flat_by_moves_up_on_early_close(self):
        rules = settings.risk_rules()
        self.assertEqual(afterclose.flat_by_for(market.SkillCalendar().session(date(2026, 11, 27)), rules),
                         dtime(12, 55))
        self.assertEqual(afterclose.flat_by_for(market.SkillCalendar().session(date(2026, 11, 18)), rules),
                         dtime(15, 55))


if __name__ == "__main__":
    unittest.main()
