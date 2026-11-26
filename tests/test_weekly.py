"""Uri's weekly paper-vs-model check: Swing's and Bumi's daily records, and when and what Uri posts."""
import json
import tempfile
import unittest
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import head, tradelog, weekly
from app.market import Session

NY = ZoneInfo("America/New_York")


def sw(day, paper=10.0, model=8.0, pt=1, mt=1, slips=(0.3,), flat=True, halt=None, off=None):
    return {"day": day, "mode": "paper", "paper_pnl": paper, "paper_trades": pt, "model_pnl": model, "model_trades": mt,
            "v1_pnl": 5.0, "v1_trades": 1, "fills": [{"slip_bp": x} for x in slips], "flat_after_close": flat,
            "halt_why": halt, "skips": 0, "outages": 0, "off": off}


def bu(day, fills=(), vix=26.0):
    return {"day": day, "mode": "paper", "plan_orders": 0, "vix": vix, "calm": False,
            "fills": [{"sym": "QLD", "side": "buy", "qty": 10, "price": 100.05, "open": 100.0, "slip_bp": s} for s in fills],
            "filled_all": True if fills else None}


class Text(unittest.TestCase):
    def test_on_track_week(self):
        days = [f"2026-11-{d}" for d in (30,)] + [f"2026-12-0{d}" for d in range(1, 5)]
        text, details = weekly.weekly_text(date(2026, 11, 30), date(2026, 12, 4), [sw(d) for d in days], [sw(d) for d in days],
                                           [bu(d) for d in days], [bu(d) for d in days], 5)
        self.assertTrue(text.startswith("📈 **Weekly check · Nov 30 – Dec 4**"))
        self.assertIn("**Swing** · ✅ on track", text)
        self.assertIn("5 trades (model 5) · paper **+$50** vs model +$40 · fills +0.3 bp vs model", text)
        self.assertIn("Go-live: week 1 of 6 · 5 of 30 trades", text)
        self.assertIn("**Bumi** · ⏳ waiting for its rules", text)
        self.assertIn("plans made 5 of 5 days", text)
        self.assertEqual([b for b, _ in details], ["Swing", "Bumi"])

    def test_flags(self):
        week = [sw("2026-12-01", slips=(2.5, 2.0), flat=False, halt="daily loss limit hit"), sw("2026-12-02", pt=3, mt=1)]
        head_, detail, flags = weekly.swing_section(week, week)
        self.assertIn("⚠️ needs a look", head_)
        self.assertTrue(any("worse than the model" in f for f in flags))
        self.assertTrue(any("not flat" in f for f in flags))
        self.assertTrue(any("safety net" in f for f in flags))
        bh, _, bflags = weekly.bumi_section([bu("2026-12-01", fills=(15.0,))], [bu("2026-12-01", fills=(15.0,))], 2)
        self.assertIn("⚠️ needs a look", bh)
        self.assertTrue(any("official open" in f for f in bflags) and any("1 of 2" in f for f in bflags))

    def test_bumi_counts_rebalances_toward_the_gate(self):
        allr = [bu("2026-12-01", fills=(1.0,)), bu("2026-12-08", fills=(2.0,)), bu("2026-12-09")]
        h, _, _ = weekly.bumi_section(allr[1:], allr, 2)
        self.assertIn("Go-live: 2 of 3 rebalances · fills +1.5 bp", h)


class Cal:
    def session(self, d):
        return Session(d, dtime(9, 30), dtime(16, 0)) if d.weekday() < 5 and d != date(2026, 11, 26) else None


class Due(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.log = tradelog.TradeLog(Path(t.name) / "t.db"); self.addCleanup(self.log.close)
        for d in ("2026-12-01", "2026-12-04"):
            self.log.set_fleet(f"daily:swing:{d}", json.dumps(sw(d)))
            self.log.set_fleet(f"daily:bumi:{d}", json.dumps(bu(d)))

    def at(self, d, h, m=0):
        return datetime(d.year, d.month, d.day, h, m, tzinfo=NY)

    def test_only_on_the_weeks_last_market_day_after_five(self):
        self.assertIsNone(head.weekly_plan(self.log, Cal(), self.at(date(2026, 12, 3), 17, 30)))   # Thursday
        self.assertIsNone(head.weekly_plan(self.log, Cal(), self.at(date(2026, 12, 4), 16, 30)))   # Friday, too early
        text, details, key = head.weekly_plan(self.log, Cal(), self.at(date(2026, 12, 4), 17, 1))
        self.assertEqual(key, "2026-12-04")
        self.assertIn("Dec 4", text)
        self.assertIn("2 trades (model 2)", text)                   # Tue and Fri records only
        self.log.set_fleet("weekly:2026-12-04", "posted")
        self.assertIsNone(head.weekly_plan(self.log, Cal(), self.at(date(2026, 12, 4), 17, 2)))

    def test_holiday_week_posts_on_the_last_open_day(self):
        self.log.set_fleet("daily:swing:2026-11-25", json.dumps(sw("2026-11-25")))
        cal = Cal()
        self.assertIsNotNone(head.weekly_plan(self.log, cal, self.at(date(2026, 11, 27), 17, 1)))  # Friday open, Thursday shut

    def test_prefix_lookup(self):
        self.assertEqual([k for k, _ in self.log.fleet_prefix("daily:swing:")], ["daily:swing:2026-12-01", "daily:swing:2026-12-04"])


if __name__ == "__main__":
    unittest.main()
