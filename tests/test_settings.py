import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import settings, strategies


class RiskRulesTest(unittest.TestCase):
    def test_repo_risk_rules_load_and_are_paper(self):
        rules = settings.risk_rules()
        self.assertIs(rules["paper"], True)
        self.assertEqual(rules["max_loss_per_trade_usd"], 50)

    def test_refuses_live_risk_config(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "risk.json").write_text(json.dumps({"paper": False}))
            with self.assertRaises(settings.SettingsError):
                settings.risk_rules(Path(d))


class AlpacaPaperGuardTest(unittest.TestCase):
    def test_refuses_live_alpaca(self):
        env = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_PAPER": "false"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(settings.SettingsError):
                settings.alpaca_settings()

    def test_accepts_paper(self):
        env = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_PAPER": "true"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(settings.alpaca_settings().paper)

    def test_missing_key_names_the_variable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(settings.SettingsError, "ALPACA_API_KEY"):
                settings.alpaca_settings()


class DiscordSettingsTest(unittest.TestCase):
    def test_non_numeric_id_is_rejected(self):
        env = {k: "1" for k in ("DISCORD_GUILD_ID", "DISCORD_OWNER_ID", "DISCORD_CHANNEL_SETUPS",
                                "DISCORD_CHANNEL_CLOSED_TRADES", "DISCORD_CHANNEL_DAILY_SUMMARY",
                                "DISCORD_CHANNEL_SYSTEM")}
        env["DISCORD_BOT_TOKEN"] = "t"
        env["DISCORD_OWNER_ID"] = "not-a-number"
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(settings.SettingsError, "DISCORD_OWNER_ID"):
                settings.discord_settings()


class ClosedTradesChannelTest(unittest.TestCase):
    BASE = {"DISCORD_BOT_TOKEN": "t", "DISCORD_GUILD_ID": "1", "DISCORD_OWNER_ID": "2", "DISCORD_CHANNEL_SETUPS": "3",
            "DISCORD_CHANNEL_DAILY_SUMMARY": "5", "DISCORD_CHANNEL_SYSTEM": "6"}

    def test_new_name(self):
        with mock.patch.dict(os.environ, {**self.BASE, "DISCORD_CHANNEL_CLOSED_TRADES": "44"}, clear=True):
            self.assertEqual(settings.discord_settings().channel_closed_trades, 44)

    def test_old_name_still_works(self):
        with mock.patch.dict(os.environ, {**self.BASE, "DISCORD_CHANNEL_TRADES": "4"}, clear=True):
            self.assertEqual(settings.discord_settings().channel_closed_trades, 4)

    def test_missing_names_the_new_variable(self):
        with mock.patch.dict(os.environ, self.BASE, clear=True):
            with self.assertRaisesRegex(settings.SettingsError, "DISCORD_CHANNEL_CLOSED_TRADES"):
                settings.discord_settings()


class StrategiesTest(unittest.TestCase):
    def test_orb_bot_loads_with_decided_v1_settings(self):
        orb = strategies.load("orb")
        self.assertEqual(orb.id, "orb")
        self.assertTrue(orb.enabled)
        s = orb.settings
        self.assertEqual(s["scan_window"], {"start": "09:50", "end": "11:30"})
        self.assertEqual(s["exit"], {"stop": "or-mid", "target": "2R"})
        self.assertEqual(s["alerts"]["max_per_day"], 5)
        self.assertEqual(s["min_volume_x"], 1.0)
        self.assertEqual(s["focus_list"]["top_n_by_dollar_volume"], 150)

    def test_enabled_bots(self):
        self.assertEqual([s.id for s in strategies.load_enabled()], ["orb"])

    def test_unknown_strategy(self):
        with self.assertRaises(settings.SettingsError):
            strategies.load("nope")

    def test_id_mismatch_is_caught(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "orb.json").write_text(json.dumps({"id": "other"}))
            with self.assertRaises(settings.SettingsError):
                strategies.load("orb", Path(d))


if __name__ == "__main__":
    unittest.main()
