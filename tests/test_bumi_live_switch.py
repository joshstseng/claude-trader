"""Bumi's live switch (paper-phase item 3): three settings must agree, sizing, the sanity cap, the new-buy breakers and
Bumi-only controls. Nothing here touches a real account."""
import os
import unittest
from unittest import mock

from app import bumi_live as L, bumi_run as R, settings
from tests.test_bumi_live import PX, S, Base, Broker, plan

LIVE = {"BUMI_MODE": "live", "ALPACA_PAPER": "false", "BUMI_LIVE_CONFIRM": "real-money"}


class Switch(unittest.TestCase):
    def test_live_needs_all_three_settings(self):
        with mock.patch.dict(os.environ, LIVE, clear=True):
            self.assertEqual(L.mode(), "live")
        for drop in LIVE:
            env = {k: v for k, v in LIVE.items() if k != drop}
            if drop == "BUMI_MODE":
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(L.mode(), "shadow")        # no live mode asked for
                continue
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(settings.SettingsError):
                L.mode()
        with mock.patch.dict(os.environ, {**LIVE, "BUMI_LIVE_CONFIRM": "yes"}, clear=True), self.assertRaises(settings.SettingsError):
            L.mode()

    def test_only_an_allowed_caller_gets_live_keys(self):
        env = {"ALPACA_PAPER": "false", "ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(settings.SettingsError):
                settings.alpaca_settings()                    # Swing, Orbi, Uri: never live
            self.assertFalse(settings.alpaca_settings(allow_live=True).paper)
        with mock.patch.dict(os.environ, {**env, "ALPACA_PAPER": "true"}, clear=True):
            self.assertTrue(settings.alpaca_settings(allow_live=True).paper)
        with mock.patch.dict(os.environ, {**env, "ALPACA_PAPER": "maybe"}, clear=True), self.assertRaises(settings.SettingsError):
            settings.alpaca_settings(allow_live=True)

    def test_size_fraction(self):
        for raw, want in ((None, 1.0), ("0.25", .25), ("1", 1.0)):
            with mock.patch.dict(os.environ, {} if raw is None else {"BUMI_SIZE_FRACTION": raw}, clear=True):
                self.assertEqual(L.size_fraction(), want)
        for bad in ("0", "1.5", "-1", "abc"):
            with mock.patch.dict(os.environ, {"BUMI_SIZE_FRACTION": bad}, clear=True), self.assertRaises(settings.SettingsError):
                L.size_fraction()


class Sizing(Base):
    def test_live_trades_a_quarter_of_the_account(self):
        b = Broker(equity=20000.0)
        with mock.patch.dict(os.environ, {"BUMI_SIZE_FRACTION": "0.25"}, clear=True):
            rec = L.decide(plan(actions={"QQQ": "buy"}, targets={"QLD": .25}), S, self.state, PX, "live", b)
        o = rec["orders"][0]
        self.assertEqual((o["sym"], o["side"]), ("QLD", "buy"))
        self.assertEqual(o["qty"], int(20000 * .25 * .25 * (1 - L.CASH_BUFFER) / 100.0))   # 12 sh, not 49
        self.assertEqual(rec["mode"], "live")

    def test_sanity_check_drops_buys_that_would_borrow(self):
        b = Broker(held={"QQQ": 100}, equity=50000.0)                  # $50k of QQQ already, no cash left
        with mock.patch.dict(os.environ, {}, clear=True):
            rec = L.decide(plan(actions={"QQQ": "buy"}, targets={"QLD": .25}), S, self.state, PX, "paper", b)
        self.assertFalse([o for o in rec["orders"] if o["side"] == "buy"])
        self.assertTrue(any("sanity check" in n for n in rec["notes"]))

    def test_paused_buys_keep_the_sells(self):
        self.state.doc["buys_paused"] = "down 16% from its peak"
        b = Broker(held={"SSO": 10}, equity=50000.0)
        with mock.patch.dict(os.environ, {}, clear=True):
            rec = L.decide(plan(actions={"QQQ": "buy", "SPY": "sell"}, targets={"QLD": .25}), S, self.state, PX, "paper", b)
        self.assertEqual([(o["sym"], o["side"]) for o in rec["orders"]], [("SSO", "sell")])
        self.assertTrue(any("new buys paused" in n for n in rec["notes"]))


class Breakers(Base):
    def test_bad_day_pauses_new_buys_once(self):
        self.assertIsNone(L.track_equity(self.state, "2026-12-01", 20000.0, .25, S))
        self.assertIsNone(L.track_equity(self.state, "2026-12-02", 19800.0, .25, S))     # -4% on the $5k traded
        alert = L.track_equity(self.state, "2026-12-03", 19350.0, .25, S)                # -9% on the money traded
        self.assertEqual(alert[0], "bad_day")
        text = R.breaker_text(*alert)
        self.assertIn("Nothing was sold because of this", text); self.assertIn("-7.5%", text); self.assertIn("/resume-bumi", text)
        self.assertLess(len(text), 1900)
        self.assertTrue(self.state.doc["buys_paused"])
        nxt = L.track_equity(self.state, "2026-12-04", 19000.0, .25, S)                  # no second bad-day pause...
        self.assertEqual(nxt[0], "drawdown")                                             # ...but the slide is now -19%
        self.assertEqual(nxt[1], "down 19.0% from its peak (alert at -15%)")
        self.assertIsNone(L.track_equity(self.state, "2026-12-04", 18000.0, .25, S))     # once a day

    def test_drawdown_alerts_once_and_keeps_trading(self):
        eq = 50000.0
        L.track_equity(self.state, "2026-12-01", eq, 1.0, S)
        alerts = []
        for d in ("2026-12-02", "2026-12-03", "2026-12-04", "2026-12-07", "2026-12-08"):
            eq *= .955                                                                    # -4.5% a day, never a bad day
            alerts.append(L.track_equity(self.state, d, eq, 1.0, S))
        hits = [a for a in alerts if a]
        self.assertEqual(len(hits), 1)                                                    # one alert per slide
        self.assertEqual(hits[0][0], "drawdown")
        self.assertIsNone(self.state.doc.get("buys_paused"))                              # Bumi keeps trading
        text = R.breaker_text(*hits[0])
        self.assertIn("Bumi keeps trading as normal", text); self.assertIn("once every 5 years", text)
        L.track_equity(self.state, "2026-12-09", 60000.0, 1.0, S)                         # new peak re-arms it
        self.assertFalse(self.state.doc["equity_track"]["dd_alerted"])

class Controls(Base):
    def test_pause_resume_flatten(self):
        b = Broker(held={"QLD": 10})
        b.close_all = lambda: b.held.clear()
        text, ack = R.bot_command("pause:bumi", self.state, "live", b)
        self.assertTrue(self.state.doc["paused"]); self.assertEqual(ack, "paused")
        self.state.doc["buys_paused"] = "a bad day"
        text, ack = R.bot_command("resume:bumi", self.state, "live", b)
        self.assertFalse(self.state.doc["paused"]); self.assertIsNone(self.state.doc["buys_paused"]); self.assertIn("a bad day", text)
        text, ack = R.bot_command("flatten:bumi", self.state, "live", b)
        self.assertTrue(self.state.doc["paused"]); self.assertEqual(b.held, {}); self.assertIn("flattened", ack)
        self.assertEqual(R.bot_command("pause:swing", self.state, "live", b), (None, "unknown command 'pause:swing', ignored"))


if __name__ == "__main__":
    unittest.main()
