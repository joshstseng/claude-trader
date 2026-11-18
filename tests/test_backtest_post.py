"""The #backtests summary message."""

import os
import unittest
from unittest import mock

from app import settings
from app.backtest import post

M = {"trades": 683, "win_rate": 0.42, "avg_r": -0.038, "avg_usd": -0.95, "total_usd": -650.0,
     "max_dd_usd": -1664.0, "target": 116, "stop": 308, "flat": 259, "avg_r_gross": 0.018}
BASE = {"run_id": 1, "label": "baseline", "from": "2024-11-01", "to": "2026-11-17", "code": "6d1a3f6",
        "headline": M, "settings": {"overrides": []}}


class SummaryTest(unittest.TestCase):
    def test_baseline(self):
        self.assertEqual(post.summary(BASE, BASE).splitlines(), [
            "**Backtest #1: baseline**",
            "Nov 1, 2024 → Nov 17, 2026 · 683 trades · win rate 42% · **−0.038R a trade** (−$0.95) · "
            "total **−$650** · worst drawdown −$1,664",
            "✅ 116 target · ❌ 308 stop · ➖ 259 flat · before costs +0.018R",
            "📉 loses money after costs · full report attached · code `6d1a3f6`"])

    def test_variation_is_compared_with_the_baseline(self):
        run = {**BASE, "run_id": 2, "label": "1R target", "settings": {"overrides": ["exit.target=1R"]},
               "headline": {**M, "avg_r": 0.012, "avg_usd": 0.5, "total_usd": 340.0, "trades": 700}}
        text = post.summary(run, BASE)
        self.assertIn("Changed: `exit.target=1R`", text)
        self.assertIn("vs baseline (#1): **+0.050R a trade better** · total +$990 · trades +17", text)
        self.assertIn("📈 has an edge after costs", text)


class WhoPostsTest(unittest.TestCase):
    """Each bot posts its own backtests; the default bot tags other strategies' runs."""

    def test_orb_runs_post_as_orb_bot_without_a_tag(self):
        with mock.patch.dict(os.environ, {"STRATEGY": ""}, clear=False):
            os.environ.pop("DISCORD_BOT_TOKEN_ORB", None)
            self.assertEqual(post.poster_for("orb"), (None, True))

    def test_a_strategy_with_its_own_bot_posts_as_itself(self):
        with mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN_DEMO": "demo-token"}):
            self.assertEqual(post.poster_for("demo"), ("demo-token", True))

    def test_a_strategy_without_a_bot_is_tagged(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_BOT_TOKEN_DEMO", None)
            self.assertEqual(post.poster_for("demo"), (None, False))
        demo = {**BASE, "run_id": 7, "label": "demo", "settings": {"strategy": {"id": "demo"}, "overrides": []}}
        self.assertTrue(post.summary(demo, None, show_tag=True).startswith("**[DEMO] Backtest #7: demo**"))


class ChannelSettingTest(unittest.TestCase):
    def test_optional(self):
        with mock.patch.dict(os.environ, {"DISCORD_CHANNEL_BACKTESTS": ""}):
            self.assertIsNone(settings.discord_backtests_channel())
        with mock.patch.dict(os.environ, {"DISCORD_CHANNEL_BACKTESTS": "123"}):
            self.assertEqual(settings.discord_backtests_channel(), 123)
        with mock.patch.dict(os.environ, {"DISCORD_CHANNEL_BACKTESTS": "abc"}):
            with self.assertRaises(settings.SettingsError):
                settings.discord_backtests_channel()


if __name__ == "__main__":
    unittest.main()
