"""Step 2b.4: the head bot (watchdog, fleet summary, /fleet, global pause, /flatten-all via the
commands table) and the trading bot's side (answering commands, watching the head)."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import head, market, settings, tradelog
from app.flatten import FlattenReport

REPO = Path(__file__).resolve().parent.parent
NY = market.NY
DAY = date(2026, 11, 19)
SESSION = market.Session(DAY, dtime(9, 30), dtime(16, 0))


def et(h, m=0, d=DAY):
    return datetime.combine(d, dtime(h, m), tzinfo=NY).astimezone(timezone.utc)


def beat(bot, at: datetime, note="running"):
    return {"bot": bot, "at": at.isoformat(timespec="seconds"), "note": note}


class WatchdogTest(unittest.TestCase):
    def test_a_silent_bot_pings_once_then_says_its_back(self):
        w = head.Watchdog(exclude={"head"})
        now = et(10, 30)
        beats = [beat("orb", now - timedelta(minutes=4)), beat("head", now - timedelta(hours=1))]
        msgs = w.check(beats, now, window=True)
        self.assertEqual(len(msgs), 1)
        self.assertIn("ORB bot is silent", msgs[0][0])
        self.assertTrue(msgs[0][1])                                   # @mention
        self.assertEqual(w.check(beats, now + timedelta(minutes=1), window=True), [])   # once per outage
        back = w.check([beat("orb", now + timedelta(minutes=5))], now + timedelta(minutes=5, seconds=10), True)
        self.assertEqual(len(back), 1)
        self.assertIn("ORB bot is back", back[0][0])
        self.assertFalse(back[0][1])

    def test_fresh_bots_and_quiet_hours_dont_ping(self):
        w = head.Watchdog(exclude={"head"})
        now = et(10, 30)
        self.assertEqual(w.check([beat("orb", now - timedelta(seconds=170))], now, True), [])
        self.assertEqual(w.check([beat("orb", now - timedelta(minutes=30))], now, False), [])   # outside window

    def test_retired_bots_are_not_watched(self):
        w = head.Watchdog(exclude={"head"})
        now = et(10, 30)
        self.assertEqual(w.check([beat("demo", now - timedelta(days=4))], now, True), [])

    def test_the_trading_bot_watches_only_the_head(self):
        w = head.head_watchdog()
        now = et(10, 30)
        beats = [beat("orb", now - timedelta(hours=2)), beat("head", now - timedelta(minutes=6))]
        msgs = w.check(beats, now, True)
        self.assertEqual(len(msgs), 1)
        self.assertIn("Head bot is silent", msgs[0][0])
        self.assertIn("Trading carries on", msgs[0][0])
        fresh = head.head_watchdog()
        self.assertEqual(fresh.check([beat("head", now - timedelta(minutes=4))], now, True), [])   # 5-min limit

    def test_no_head_yet_means_nothing_to_say(self):
        self.assertEqual(head.head_watchdog().check([beat("orb", et(10))], et(10, 30), True), [])

    def test_windows(self):
        self.assertFalse(head.watching(et(8, 59), SESSION))
        self.assertTrue(head.watching(et(9, 0), SESSION))
        self.assertTrue(head.watching(et(16, 15), SESSION))           # the 4:15 summary is watched too
        self.assertFalse(head.watching(et(16, 25), SESSION))
        self.assertFalse(head.watching(et(12), None))                 # market closed
        early = market.Session(DAY, dtime(9, 30), dtime(13, 0))
        self.assertFalse(head.watching(et(13, 30), early))
        self.assertTrue(head.in_market_hours(et(9, 30), SESSION))
        self.assertFalse(head.in_market_hours(et(9, 29), SESSION))
        self.assertFalse(head.in_market_hours(et(16, 1), SESSION))


class FleetDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = tradelog.TradeLog(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def trade(self, strat, day, sym, *, alerted=True, order=None, entry=100.0, stop=98.0):
        run = self.log.start_run(strat, "live", {}, date_from=day, date_to=day)
        self.log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop, target,"
                            " created_at) VALUES (?, ?, 'live', ?, ?, 'pass', ?, ?, 104, 'x')",
                            (run, strat, day, sym, entry, stop))
        sid = self.log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
        self.log.record_alert(sid, sent=alerted, held_reason=None if alerted else "daily alert cap (5)")
        if order is not None:
            cid = f"{strat}-{day}-{sid}"
            self.log.add_order(sid, cid, sym, 10, entry, stop, 104)
            self.log.update_order(cid, **order)
        return sid

    def test_commands_are_carried_out_once_per_bot(self):
        cid = self.log.add_command("flatten", by="me")
        self.assertEqual([r["id"] for r in self.log.pending_commands("orb")], [cid])
        self.log.ack_command(cid, "orb", "closed 1")
        self.log.ack_command(cid, "orb", "again")                    # a retry can't double-answer
        self.assertEqual(self.log.pending_commands("orb"), [])
        self.assertEqual([r["id"] for r in self.log.pending_commands("vwap")], [cid])   # other bots still owe it
        self.assertEqual([(a["bot"], a["result"]) for a in self.log.command_acks(cid)], [("orb", "closed 1")])

    def test_old_commands_are_ignored(self):
        cid = self.log.add_command("flatten")
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        self.log.db.execute("UPDATE fleet_commands SET created_at = ? WHERE id = ?", (old, cid))
        self.assertEqual(self.log.pending_commands("orb"), [])

    def test_numbers_and_summary(self):
        day = "2026-11-19"
        self.trade("orb", day, "TSLA", order=dict(status="closed", filled_qty=10, filled_price=100.0,
                                                    exit_price=104.0, pnl_usd=40.0))
        self.trade("orb", day, "NVDA", order=dict(status="filled", filled_qty=10, filled_price=101.0))
        self.trade("orb", day, "AMD", alerted=False)
        self.trade("orb", "2026-11-18", "CMG", order=dict(status="closed", filled_qty=10, filled_price=100.0,
                                                           exit_price=99.0, pnl_usd=-10.0))
        self.trade("demo", day, "AAPL", order=dict(status="closed", filled_qty=10, filled_price=100.0,
                                                    exit_price=98.0, pnl_usd=-20.0))
        n = head.bot_numbers(self.log, "orb", day)
        self.assertEqual((n["signals"], n["alerts"], n["orders"], n["closed"], n["wins"]), (3, 2, 2, 1, 1))
        self.assertEqual((n["day_pnl"], n["all_time"], n["open"]), (40.0, 30.0, 1))
        self.assertAlmostEqual(n["at_risk"], 30.0)                    # NVDA: (101 - 98) x 10 sh
        self.assertEqual(head.bot_numbers(self.log, "demo", day)["day_pnl"], -20.0)   # kept apart by bot

        now = et(16, 35)
        self.log.beat("orb")
        self.log.beat("head")
        self.assertEqual(head.fleet_bots(self.log, datetime.now(timezone.utc), day), ["demo", "orb"])
        text = head.summary_text([head.bot_numbers(self.log, b, day) for b in ("demo", "orb")], day, False)
        self.assertIn("🧭 **Fleet · Thu Nov 19**", text)
        self.assertIn("\n\n**ORB bot** · **+$40.00** · 1 closed (1 won) · ⚠️ 1 still open\n"
                      "-# 3 signals · 2 alerts · 2 orders · all-time +$30.00\n\n", text)
        self.assertIn("**Fleet today +$20.00**", text)
        one = head.summary_text([head.bot_numbers(self.log, "orb", day)], day, True)
        self.assertIn("global pause is **on**", one)
        self.assertNotIn("Fleet today", one)                         # one bot: no total line
        del now

    def test_status(self):
        day = datetime.now(NY).strftime("%Y-%m-%d")
        self.trade("orb", day, "NVDA", order=dict(status="filled", filled_qty=10, filled_price=101.0))
        self.log.beat("orb", "running")
        self.log.set_fleet("global_pause", "on")
        text = head.status_text(self.log, datetime.now(timezone.utc), SESSION)
        self.assertIn("global pause on", text)
        self.assertIn("**ORB bot** 🟢 running", text)
        self.assertIn("Money at risk across bots: $30.00", text)

    def test_flatten_report(self):
        acks = [{"bot": "orb", "result": "closed 2"}]
        text = head.flatten_report(acks, ["orb", "vwap"])
        self.assertIn("✅ **ORB bot**: closed 2", text)
        self.assertIn("⚠️ **VWAP bot**: no answer", text)
        self.assertIn("No trading bot is alive", head.flatten_report([], []))


class FakeBot:
    def __init__(self, rep):
        self.flattener, self.rep, self.posted, self.after = object(), rep, [], []

    async def flatten_now(self, phase):
        self.phase = phase
        return self.rep, self.rep.text() if self.rep.anything else "nothing"

    async def post_system(self, text, ping=False):
        self.posted.append(text)

    async def after_flatten(self, rep, text):
        self.after.append(text)


class TradingBotSideTest(unittest.TestCase):
    def test_flatten_command(self):
        from app.__main__ import run_fleet_command
        rep = FlattenReport("flatten all", exits=[("TSLA", 6, "flatten", 400.0, 12.5)], cancelled_entries=["AMD"])
        bot = FakeBot(rep)
        result = asyncio.run(run_fleet_command(bot, "flatten"))
        self.assertEqual(bot.phase, "flatten all")
        self.assertEqual(result, "closed 1 · cancelled 1 unfilled")
        self.assertIn("Flattened by the head bot's /flatten-all", bot.posted[0])
        self.assertEqual(len(bot.after), 1)
        self.assertEqual(asyncio.run(run_fleet_command(FakeBot(FlattenReport("flatten all")), "flatten")),
                         "nothing was open")
        self.assertIn("unknown", asyncio.run(run_fleet_command(bot, "dance")))

    def test_the_bot_answers_the_heads_command(self):
        from app import __main__ as m
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            cid = log.add_command("flatten")
            bot = FakeBot(FlattenReport("flatten all"))

            async def go():
                t = asyncio.create_task(m.fleet_commands(bot, every_s=0.05, trade_log=log))
                for _ in range(100):
                    await asyncio.sleep(0.02)
                    if log.command_acks(cid):
                        break
                t.cancel()
            asyncio.run(go())
            self.assertEqual([(a["bot"], a["result"]) for a in log.command_acks(cid)], [("orb", "nothing was open")])
            log.close()


class HeadBotTest(unittest.TestCase):
    def test_flatten_all_pauses_asks_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.beat("orb")
            cfg = head.HeadSettings("x", 1, 2, 3, 4)

            async def go():
                bot = head.make_head_bot(cfg, log, market.SkillCalendar())

                async def orb_answers():
                    while True:
                        for c in log.pending_commands("orb"):
                            log.ack_command(c["id"], "orb", "closed 1")
                        await asyncio.sleep(0.02)
                t = asyncio.create_task(orb_answers())
                text = await bot.flatten_all("me", wait_s=5, poll_s=0.02)
                t.cancel()
                return text
            text = asyncio.run(go())
            self.assertTrue(log.global_pause())
            self.assertIn("✅ **ORB bot**: closed 1", text)
            log.close()

    def run_summary(self, log, times, calendar=None):
        """Call summary_if_due at each ET time; return what it posted: [(text, details)]."""
        cfg = head.HeadSettings("x", 1, 2, 3, 4)
        posted = []

        async def go():
            bot = head.make_head_bot(cfg, log, calendar or market.SkillCalendar())

            async def post_summary(text, details, day):
                posted.append((day, text, details))
            bot.post_summary = post_summary
            return [await bot.summary_if_due(t) for t in times]
        return asyncio.run(go()), posted

    def test_summary_waits_for_every_bot_then_posts_once(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.beat("orb")
            log.beat("head")
            day = DAY.isoformat()
            r1, _ = self.run_summary(log, [et(16, 0), et(16, 20)])     # before 4:15; no report yet
            self.assertEqual(r1, [False, False])
            log.save_report("orb", day, "**[ORB] Thu Nov 19**\nTSLA ❌ stop −1.00R")
            r2, posted = self.run_summary(log, [et(16, 21), et(16, 40)])
            self.assertEqual(r2, [True, False])                        # posted once
            day_, text, details = posted[0]
            self.assertEqual(day_, day)
            self.assertIn("Fleet · Thu Nov 19", text)
            self.assertIn("in the thread", text)
            self.assertEqual(details, [("orb", "**[ORB] Thu Nov 19**\nTSLA ❌ stop −1.00R")])
            log.close()

    def test_deadline_names_a_bot_that_didnt_report(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.beat("orb")
            r, posted = self.run_summary(log, [et(16, 59), et(17, 0)])
            self.assertEqual(r, [False, True])
            self.assertIn("No summary from **ORB bot**", posted[0][1])
            self.assertEqual(posted[0][2], [])
            log.close()

    def test_catch_up_for_the_previous_market_day(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.save_report("orb", "2026-11-19", "Thursday's summary")
            friday_morning = et(8, 0, d=date(2026, 11, 20))
            r, posted = self.run_summary(log, [friday_morning, friday_morning])
            self.assertEqual(r, [True, False])
            self.assertEqual(posted[0][0], "2026-11-19")
            # a day without reports (e.g. before the head existed) is never posted late
            monday = et(8, 0, d=date(2026, 11, 23))
            self.assertEqual(self.run_summary(log, [monday])[0], [False])
            log.close()

    def test_a_day_the_old_head_already_posted_isnt_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.save_report("orb", DAY.isoformat(), "x")
            log.set_fleet("head_summary_day", DAY.isoformat())
            self.assertEqual(self.run_summary(log, [et(16, 40)])[0], [False])
            log.close()

    def test_long_reports_split_on_lines(self):
        text = "\n".join(f"line {i} " + "x" * 80 for i in range(60))
        parts = head.chunks(text, 1900)
        self.assertTrue(all(len(p) <= 1900 for p in parts))
        self.assertEqual("\n".join(parts), text)
        self.assertEqual(head.chunks("y" * 4000, 1900)[0], "y" * 1900)


class DailyReportTest(unittest.TestCase):
    def test_the_bot_hands_its_summary_to_the_head(self):
        from app.__main__ import daily_report
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            bot = FakeBot(FlattenReport("x"))
            bot.daily = []

            async def post_daily(text):
                bot.daily.append(text)
            bot.post_daily = post_daily
            asyncio.run(daily_report(bot, "2026-11-19", trade_log=log)("summary text"))
            self.assertEqual([(r["bot"], r["text"]) for r in log.reports("2026-11-19")], [("orb", "summary text")])
            self.assertEqual(bot.daily, [])                         # not posted by the bot itself
            asyncio.run(daily_report(bot, "2026-11-19", trade_log=log)("rerun"))   # a rerun replaces it
            self.assertEqual([r["text"] for r in log.reports("2026-11-19")], ["rerun"])
            log.close()

            class Broken:
                def save_report(self, *a):
                    raise RuntimeError("database down")
            asyncio.run(daily_report(bot, "2026-11-19", trade_log=Broken())("fallback"))
            self.assertEqual(bot.daily, ["fallback"])               # never lost


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = tradelog.TradeLog(Path(self.tmp.name) / "t.db")
        head.NAMES.clear()

    def tearDown(self):
        head.NAMES.clear()
        self.log.close()
        self.tmp.cleanup()

    def test_heartbeats_keep_the_discord_name_and_status(self):
        self.log.beat("orb", "running", name="Orbi", status="**ORB bot** running")
        self.log.beat("orb", "paused (global)")                   # a beat without them keeps the last ones
        r = self.log.heartbeats()[0]
        self.assertEqual((r["note"], r["name"], r["status"]), ("paused (global)", "Orbi", "**ORB bot** running"))

    def test_find_a_bot_by_any_name(self):
        self.log.beat("orb", name="Orbi")
        self.log.beat("head", name="Uri")
        beats = self.log.heartbeats()
        head.learn_names(beats)
        for q, want in (("Orbi", "orb"), ("orbi", "orb"), ("orb", "orb"), ("Uri", "head"), ("head", "head"),
                        ("all", "all"), ("", "all"), ("nobody", None)):
            self.assertEqual(head.find_bot(beats, q), want, q)
        self.assertEqual(head.bot_name("orb"), "Orbi")

    def test_a_trading_bots_status(self):
        now = datetime.now(timezone.utc)
        self.log.beat("orb", "running", name="Orbi", status="Focus list: 150 stocks\nNext check 10:05 AM ET")
        head.learn_names(self.log.heartbeats())
        text = head.bot_status_text(self.log, "orb", now)
        self.assertIn("**Orbi** 🟢 running", text)
        self.assertIn("Next check 10:05 AM ET", text)
        self.assertIn("Today: 0 orders", text)

    def test_the_heads_own_status(self):
        self.log.beat("orb", name="Orbi")
        self.log.beat("head", name="Uri")
        head.learn_names(self.log.heartbeats())
        now = datetime.now(timezone.utc)
        text = head.head_status_text(self.log, now, SESSION, now)
        self.assertIn("**Uri** (head bot)", text)
        self.assertIn("Watching: Orbi", text)
        self.assertIn("Global pause: off", text)
        self.assertIn("Market closed today", head.head_status_text(self.log, now, None, None))

    def test_status_command_routes_by_name(self):
        self.log.beat("orb", "running", name="Orbi", status="its own words")
        self.log.beat("head", name="Uri")
        bot = head.make_head_bot(head.HeadSettings("x", 1, 2, 3, 4), self.log, market.SkillCalendar())
        self.assertIn("its own words", bot.status_for("Orbi"))
        self.assertIn("(head bot)", bot.status_for("uri"))
        self.assertIn("Money at risk across bots", bot.status_for("all"))
        self.assertIn("No bot called **zed**. Try: all, Uri, Orbi", bot.status_for("zed"))


class FakeMsg:
    _n = 0

    def __init__(self, content):
        FakeMsg._n += 1
        self.id, self.content, self.deleted, self.edits = FakeMsg._n, content, False, 0

    async def edit(self, content=None, **kw):
        self.content, self.edits = content, self.edits + 1

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, text, **kw):
        self.silent = kw.get("silent")
        self.sent.append(FakeMsg(text))
        return self.sent[-1]

    async def fetch_message(self, mid):
        return next(m for m in self.sent if m.id == mid)


class IdleMessageTest(unittest.TestCase):
    def test_phases_and_lines_never_repeat(self):
        self.assertEqual(head.idle_phase(et(8, 0), SESSION), "premarket")
        self.assertEqual(head.idle_phase(et(10, 0), SESSION), "market")
        self.assertEqual(head.idle_phase(et(16, 30), SESSION), "closed")
        self.assertEqual(head.idle_phase(et(10, 0), None), "day_off")
        last = None
        for _ in range(30):
            text, line = head.idle_text("market", last)
            self.assertNotEqual(line, last)
            self.assertIn("No live trades", text)
            last = line

    def test_posted_when_quiet_deleted_when_a_trade_starts(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            ch = FakeChannel()

            async def go():
                bot = head.make_head_bot(head.HeadSettings("x", 1, 2, 3, 4, channel_live_trades=5), log,
                                         market.SkillCalendar())

                async def idle_channel():
                    return ch
                bot.idle_channel = idle_channel
                did = [await bot.idle_check(et(9, 0)), await bot.idle_check(et(9, 1))]
                did.append(await bot.idle_check(et(10, 0)))          # the market opened: new line, same message
                run = log.start_run("orb", "live", {}, date_from=DAY.isoformat(), date_to=DAY.isoformat())
                log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop,"
                               " target, created_at) VALUES (?, 'orb', 'live', ?, 'TSLA', 'pass', 100, 98, 104, 'x')",
                               (run, DAY.isoformat()))
                sid = log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
                log.add_order(sid, "c1", "TSLA", 10, 100, 98, 104)
                log.update_order("c1", status="submitted")
                did += [await bot.idle_check(et(10, 5)), await bot.idle_check(et(10, 6))]
                log.update_order("c1", status="closed")
                did.append(await bot.idle_check(et(11, 0)))
                return did
            did = asyncio.run(go())
            self.assertEqual(did, ["posted", None, "edited", "deleted", None, "posted"])
            self.assertTrue(ch.sent[0].deleted)
            self.assertIn("🔭", ch.sent[0].content)
            self.assertTrue(ch.silent)
            self.assertEqual(json.loads(log.fleet("head_idle"))["msg"], str(ch.sent[1].id))
            log.close()

    def test_an_older_copy_of_the_head_leaves_it_alone(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.set_fleet("head_instance", "newer-copy")
            bot = head.make_head_bot(head.HeadSettings("x", 1, 2, 3, 4, channel_live_trades=5), log,
                                     market.SkillCalendar())
            self.assertIsNone(asyncio.run(bot.idle_check(et(10, 0))))
            off = head.make_head_bot(head.HeadSettings("x", 1, 2, 3, 4), log, market.SkillCalendar())
            self.assertIsNone(asyncio.run(off.idle_check(et(10, 0))))
            log.close()


class UnpingTest(unittest.TestCase):
    def test_the_summary_asks_every_bot_to_unping_that_day(self):
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            log.beat("orb")
            log.save_report("orb", DAY.isoformat(), "x")
            HeadBotTest().run_summary(log, [et(16, 30)])
            cmds = log.pending_commands("orb")
            self.assertEqual([(c["command"], c["note"]) for c in cmds], [("unping", DAY.isoformat())])
            log.close()

    def test_the_bot_takes_the_mention_off_its_own_cards(self):
        from app.__main__ import run_fleet_command
        from app.livecards import LiveCards
        with tempfile.TemporaryDirectory() as d:
            log = tradelog.TradeLog(Path(d) / "t.db")
            ch = FakeChannel()
            run = log.start_run("orb", "live", {}, date_from=DAY.isoformat(), date_to=DAY.isoformat())
            for sym in ("TSLA", "AMD"):
                log.db.execute("INSERT INTO signals (run_id, strategy, source, date, symbol, status, entry, stop,"
                               " target, created_at) VALUES (?, 'orb', 'live', ?, ?, 'pass', 100, 98, 104, 'x')",
                               (run, DAY.isoformat(), sym))
                sid = log.db.execute("SELECT max(id) FROM signals").fetchone()[0]
                msg = FakeMsg(f"<@2> ✅ **{sym}** target hit")
                ch.sent.append(msg)
                log.add_order(sid, sym, sym, 10, 100, 98, 104)
                log.update_order(sym, status="closed", closed_card_message_id=str(msg.id))
            bot = mock.Mock()
            lc = LiveCards(bot, log, None, {}, live_channel=5, closed_channel=6)

            async def channel(cid):
                return ch
            lc._channel = channel
            bot.cards = lc
            self.assertEqual(asyncio.run(run_fleet_command(bot, "unping", DAY.isoformat())),
                             "took the @mention off 2 cards")
            self.assertEqual([m.content for m in ch.sent], ["✅ **TSLA** target hit", "✅ **AMD** target hit"])
            self.assertEqual(asyncio.run(run_fleet_command(bot, "unping", DAY.isoformat())),
                             "took the @mention off 0 cards")
            self.assertEqual(asyncio.run(run_fleet_command(FakeBot(None), "unping", DAY.isoformat())),
                             "no closed-trade cards")
            log.close()


class SettingsTest(unittest.TestCase):
    def test_the_head_needs_its_own_discord_bot(self):
        env = {"DISCORD_BOT_TOKEN_HEAD": "same", "DISCORD_BOT_TOKEN": "same", "DISCORD_GUILD_ID": "1",
               "DISCORD_OWNER_ID": "2", "DISCORD_CHANNEL_SYSTEM": "3", "DISCORD_CHANNEL_DAILY_SUMMARY": "4"}
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(settings.SettingsError):
                head.head_settings()
            os.environ["DISCORD_BOT_TOKEN_HEAD"] = "own"
            self.assertEqual(head.head_settings().channel_daily_summary, 4)

    def test_bot_role_head_gets_its_own_folder(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if k not in ("STRATEGY", "BOT_ROLE")}
            env.update(TRADER_STORAGE=d, BOT_ROLE="head")
            out = subprocess.run([sys.executable, "-c", "import json; from app import paths; "
                                  "print(json.dumps([paths.BOT_ID, str(paths.DATA_DIR)]))"],
                                 cwd=REPO, env=env, capture_output=True, text=True, check=True)
            bot_id, data = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(bot_id, "head")
            self.assertEqual(Path(data), Path(d).resolve() / "bots" / "head" / "data")


if __name__ == "__main__":
    unittest.main()
