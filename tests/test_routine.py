"""The ORB bot's day: alert rules, check times, focus list, and a full-day replay of 2026-10-19."""

import asyncio
import copy
import tempfile
import unittest
from datetime import date, datetime, time as dtime
from pathlib import Path

from app import market, paths, pipeline, settings, strategies, tradelog
from app.routine import DayData, LogAlerter, OrbDay, decide_alert
from app.scheduler import SimClock, run_day

FIX = paths.SKILL_DIR / "tests" / "fixtures"
WALL = FIX / "trader-scanner" / "wall5m-2026-10-19.json.gz"
TM_DIR = FIX / "trader-timemachine"
DAY = date(2026, 10, 19)
# a small focus list from the saved day: 5 early breakouts, MPC (6th), TSLA (10:35 with volume)
FOCUS = ["CDNS", "CVX", "HUM", "ELV", "EOG", "MPC", "TSLA"]


def result(status="pass", minutes_since=1, reason=""):
    return pipeline.SignalResult("orb", "X", "2026-10-19", Path("."), status, reason,
                                 steps={"entry": pipeline.StepResult(
                                     "entry", True, 0, {"status": "triggered",
                                                         "minutes_since": minutes_since})})


class DecideAlertTest(unittest.TestCase):
    s = strategies.load("orb").settings

    def test_pass_is_sent(self):
        self.assertEqual(decide_alert(result(), sent_today=0, settings=self.s, paused=False), (True, None))

    def test_risk_block_is_held(self):
        send, why = decide_alert(result("blocked", reason="over max loss"), sent_today=0,
                                 settings=self.s, paused=False)
        self.assertFalse(send)
        self.assertIn("blocked", why)

    def test_daily_cap(self):
        send, why = decide_alert(result(), sent_today=5, settings=self.s, paused=False)
        self.assertEqual((send, why), (False, "daily alert cap (5)"))

    def test_paused(self):
        self.assertEqual(decide_alert(result(), sent_today=0, settings=self.s, paused=True),
                         (False, "bot paused"))

    def test_stale(self):
        send, why = decide_alert(result(minutes_since=26), sent_today=0, settings=self.s, paused=False)
        self.assertFalse(send)
        self.assertIn("stale", why)


class CheckTimesTest(unittest.TestCase):
    s = strategies.load("orb").settings

    def test_every_5_minutes_one_minute_after_the_bar(self):
        times = market.check_times(market.Session(DAY, dtime(9, 30), dtime(16, 0)), self.s)
        hhmm = [t.strftime("%H:%M") for t in times]
        self.assertEqual(hhmm[0], "09:51")
        self.assertEqual(hhmm[-1], "11:31")
        self.assertEqual(len(hhmm), 21)

    def test_skill_calendar_knows_holidays_and_early_closes(self):
        cal = market.SkillCalendar()
        self.assertIsNone(cal.session(date(2026, 11, 26)))                 # Thanksgiving
        self.assertTrue(cal.session(date(2026, 11, 27)).early_close)       # 1:00 PM close
        self.assertIsNone(cal.session(date(2026, 11, 21)))                 # Saturday


class FocusListTest(unittest.TestCase):
    def test_top_by_dollars_traded_plus_capped_daily_hits(self):
        data = {"A": {"meta": {"regularMarketPrice": 10, "regularMarketVolume": 1_000}},     # $10k
                "B": {"meta": {"regularMarketPrice": 100, "regularMarketVolume": 1_000}},    # $100k
                "C": {"meta": {"regularMarketPrice": 3, "regularMarketVolume": 10**9}},      # under $5
                "D": {"meta": {"regularMarketPrice": 50, "regularMarketVolume": 1_000}}}     # $50k
        fl = {"min_price": 5, "top_n_by_dollar_volume": 2, "include_daily_scan_hits": True,
              "max_daily_scan_hits": 1}
        hits = [{"symbol": "B"}, {"symbol": "A"}, {"symbol": "C"}]
        out = market.pick_focus(data, ["A", "B", "C", "D"], hits, fl)
        self.assertEqual(out["top"], ["B", "D"])
        self.assertEqual(out["daily_hits"], ["A"])          # B already in; cap of 1
        self.assertEqual(out["symbols"], ["B", "D", "A"])


class ReplayDayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        entry_dir = market.split_bundle(WALL, root / "bars")
        self.day_data = DayData(bars=WALL, entry_dir=entry_dir, timemachine_dir=TM_DIR)
        self.log = tradelog.TradeLog(root / "t.db")
        self.alerter = LogAlerter()
        self.root = root

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def bot(self, **orb_changes):
        s = strategies.load("orb")
        data = copy.deepcopy(s.settings)
        data.update(orb_changes)
        return OrbDay(strategies.Strategy(s.id, s.name, s.enabled, data), settings.risk_rules(),
                      self.log, source="replay", day=DAY.isoformat(), alerter=self.alerter,
                      runs_root=self.root / "runs", day_data=self.day_data)

    def test_full_day_on_the_simulated_clock(self):
        bot = self.bot()
        session = market.SkillCalendar().session(DAY)
        clock = SimClock(datetime.combine(DAY, dtime(7, 0), tzinfo=market.NY))
        asyncio.run(run_day(bot, session, clock, simulated=True, focus=FOCUS))

        rows = {r["symbol"]: r for r in self.log.signals(run_id=bot.run_id)}
        self.assertEqual(set(rows), set(FOCUS))
        # first come first served: the five 9:50/9:55 signals are alerted, MPC hits the cap
        alerted = [self.log.signal(sid)["symbol"] for sid, _ in self.alerter.sent]
        self.assertEqual(sorted(alerted), ["CDNS", "CVX", "ELV", "EOG", "HUM"])
        self.assertEqual(self.log.alert(rows["MPC"]["id"])["held_reason"], "daily alert cap (5)")
        # TSLA with the v1 volume check triggers at 10:35, as in test_pipeline
        self.assertEqual((rows["TSLA"]["trigger_time"], rows["TSLA"]["trigger_price"]), ("10:35", 365.75))
        self.assertIsNone(rows["TSLA"]["tm_verdict"])             # held (cap): slow steps skipped
        self.assertEqual(rows["TSLA"]["qty"], 6)                  # but the full plan is logged
        self.assertIsNone(rows["CDNS"]["tm_verdict"])             # alerted, no saved data: skipped, not fetched
        self.assertIsNotNone(self.log.run(bot.run_id)["finished_at"])

    def test_alerted_signal_gets_time_machine_odds(self):
        bot = self.bot()
        bot.premarket(["TSLA"])
        bot.tick("2026-10-19 10:36")
        row = self.log.signals(run_id=bot.run_id)[0]
        self.assertEqual(self.log.alert(row["id"])["sent"], 1)
        self.assertIsNotNone(row["tm_verdict"])                   # from saved data, no network

    def test_focus_list_failure_doesnt_crash_the_day(self):
        """Yahoo down at 8:30: retried, then an ERROR (which pings #system), no checks, the day still ends."""
        from unittest import mock
        bot = self.bot()
        closed = []

        async def after_close(b):
            closed.append(b.day)

        session = market.SkillCalendar().session(DAY)
        clock = SimClock(datetime.combine(DAY, dtime(7, 0), tzinfo=market.NY))
        with mock.patch.object(bot, "premarket", side_effect=RuntimeError("Yahoo said 429")) as pm, \
                self.assertLogs("app.scheduler", level="ERROR") as logs:
            asyncio.run(run_day(bot, session, clock, simulated=True, focus=FOCUS, after_close=after_close))
        self.assertEqual(pm.call_count, 3)
        self.assertIn("couldn't build today's focus list", logs.output[0])
        self.assertEqual(bot.checks, 0)
        self.assertEqual(closed, ["2026-10-19"])

    def test_daily_cap_counts_per_run(self):
        """Replaying the same day twice: the second run gets its own cap of 5."""
        for _ in range(2):
            bot = self.bot()
            bot.premarket(["CDNS"])
            self.assertEqual(bot.tick("2026-10-19 09:51").alerted, ["CDNS"])

    def test_live_day_resumes_after_a_restart(self):
        """A redeploy mid-morning: same run, CDNS isn't alerted again, the cap carries over."""
        def live_bot():
            s = strategies.load("orb")
            return OrbDay(s, settings.risk_rules(), self.log, source="live", day=DAY.isoformat(),
                          alerter=self.alerter, runs_root=self.root / "runs", day_data=self.day_data)
        first = live_bot()
        first.premarket(["CDNS", "CVX"])
        self.assertEqual(first.tick("2026-10-19 09:51").alerted, ["CDNS", "CVX"])
        again = live_bot()                                   # the app restarted
        self.assertTrue(again.resumed)
        self.assertEqual(again.run_id, first.run_id)
        again.premarket(["CDNS", "CVX"])
        report = again.tick("2026-10-19 09:56")
        self.assertEqual((report.signals, report.alerted), ([], []))
        self.assertEqual(self.log.alerts_sent(strategy="orb", date="2026-10-19", run_id=again.run_id), 2)

    def test_scanned_today_survives_a_restart_but_not_a_late_start(self):
        def live_bot():
            return OrbDay(strategies.load("orb"), settings.risk_rules(), self.log, source="live",
                          day=DAY.isoformat(), alerter=self.alerter, runs_root=self.root / "runs",
                          day_data=self.day_data)
        late = live_bot()                         # started after the window: no focus list, no checks
        self.assertFalse(late.scanned_today)
        again = live_bot()                        # resumed, still nothing scanned (today's real bug)
        self.assertTrue(again.resumed)
        self.assertFalse(again.scanned_today)
        again.premarket(["CDNS"])                 # a normal morning
        self.assertTrue(live_bot().scanned_today)  # and a later restart still knows

    def test_late_start_logs_but_does_not_alert_stale_triggers(self):
        bot = self.bot()
        bot.premarket(["CDNS"])                                   # broke out at 9:50
        report = bot.tick("2026-10-19 10:16")
        self.assertEqual(report.signals, [("CDNS", "pass")])
        self.assertEqual(report.alerted, [])
        self.assertIn("stale", report.held[0][1])

    def test_paused_bot_still_logs(self):
        bot = self.bot()
        bot.paused = True
        bot.premarket(["CDNS"])
        report = bot.tick("2026-10-19 09:51")
        self.assertEqual(report.held, [("CDNS", "bot paused")])
        self.assertEqual(len(self.log.signals(run_id=bot.run_id)), 1)


if __name__ == "__main__":
    unittest.main()
