"""Discord pieces that don't need a live connection: the alert's content, the buttons, pause."""

import copy
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import discord_bot, pipeline, settings, strategies
from app.state import AppState
from tests.test_pipeline import TSLA


def orb_without_volume_filter():
    s = strategies.load("orb")
    data = copy.deepcopy(s.settings)
    data["min_volume_x"] = None
    return strategies.Strategy(s.id, s.name, s.enabled, data)


class AlertMessageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.r = pipeline.run_signal(orb_without_volume_filter(), "TSLA", settings.risk_rules(),
                                    now="2026-10-19 10:15", offline=TSLA,
                                    runs_root=Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_preview_line_is_what_the_phone_shows(self):
        preview, _ = discord_bot.alert_message(12, "live", self.r)
        self.assertEqual(preview, "**[ORB] TSLA** breakout · buy $364.18 · stop $358.32 · target $375.90")

    def test_numbers_are_one_aligned_block(self):
        self.assertEqual(discord_bot.plan_block(self.r), "\n".join([
            "```",
            "Entry   $364.18   10:15 AM",
            "Stop    $358.32   −1.6%",
            "Target  $375.90   +3.2%  2R",
            "Size    8 sh      $2,913",
            "Risk    $46.88    if stopped",
            "```"]))

    def test_card_is_compact_and_complete(self):
        _, em = discord_bot.alert_message(12, "live", self.r)
        d = em.to_dict()
        self.assertEqual(d["title"], "TSLA · ORB breakout")
        self.assertNotIn("fields", d)                                   # one block, no stacked sections
        desc = d["description"]
        self.assertIn("Closed above the 9:30–9:45 high ($362.18) · volume 0.6×", desc)
        self.assertIn("✅ Risk check passed · out by 3:55 PM", desc)
        self.assertIn("🎲 **Odds:** target 4.0% · stop 25.6% · neither 70.5%", desc)
        self.assertIn("↳ _Strongly toward the stop_", desc)
        self.assertIn("📰 ", desc)
        self.assertIn("finance.yahoo.com", desc)
        self.assertNotIn("Replay of", desc)
        self.assertEqual(d["footer"]["text"],
                         "Approve = bracket order on the paper account (entry, stop, target) · #12")

    def test_missing_odds_and_news_are_left_out_not_shown_as_empty(self):
        r = pipeline.SignalResult(self.r.strategy, self.r.symbol, self.r.date, self.r.folder,
                                  self.r.status, steps={k: v for k, v in self.r.steps.items()
                                                        if k not in ("timemachine", "news")})
        desc = discord_bot.alert_message(1, "live", r)[1].description
        self.assertNotIn("Odds", desc)
        self.assertNotIn("📰", desc)

    def test_replay_alerts_are_marked(self):
        preview, em = discord_bot.alert_message(3, "replay", self.r)
        self.assertTrue(preview.startswith("REPLAY · "))
        self.assertEqual(em.title, "REPLAY · TSLA · ORB breakout")
        self.assertIn("_Replay of Mon Oct 19, 2026_", em.description)

    def test_last_tap_replaces_the_previous_one(self):
        _, em = discord_bot.alert_message(12, "live", self.r)
        t = datetime(2026, 10, 19, 14, 17, tzinfo=timezone.utc)
        em = discord_bot.with_response(em, "skip", t)
        em = discord_bot.with_response(em, "took", t)
        self.assertEqual(em.description.count("Your call"), 1)
        self.assertTrue(em.description.endswith("**Your call:** ✅ Took it · 10:17 AM ET"))

    def test_approve_and_skip_buttons(self):
        labels = lambda v: tuple(b.item.label for b in v.children)
        self.assertEqual(labels(discord_bot.decision_view("live", 12)), ("Approve", "Skip"))
        self.assertEqual(labels(discord_bot.decision_view("live", 12, chosen="skip")), ("Approve", "✓ Skipped"))
        placed = discord_bot.decision_view("live", 12, chosen="approve", locked=True)
        self.assertEqual(labels(placed), ("✓ Approved", "Skip"))
        self.assertTrue(all(b.item.disabled for b in placed.children))      # no more taps after an order
        self.assertEqual(placed.children[0].item.custom_id, "orb:approve:live:12")

    def test_alerts_from_before_1b_keep_their_took_it_button(self):
        old = discord_bot.decision_view("live", 3, chosen="took", kind="took")
        self.assertEqual(tuple(b.item.label for b in old.children), ("✓ Took it", "Skip"))

    def test_order_lines_stack_under_the_alert(self):
        _, em = discord_bot.alert_message(12, "live", self.r)
        em = discord_bot.with_order_line(em, "⏳ **Order sent** (paper): buy 8 TSLA")
        em = discord_bot.with_order_line(em, "✅ **Filled** 8 TSLA at $364.49")
        self.assertTrue(em.description.endswith("⏳ **Order sent** (paper): buy 8 TSLA\n✅ **Filled** 8 TSLA at $364.49"))


class NewsLinesTest(unittest.TestCase):
    def test_important_filing_first_then_headlines(self):
        news = {"items": [
            {"kind": "headline", "title": "H1", "link": "l1", "time": "2026-10-19T13:00:00Z", "tags": []},
            {"kind": "filing", "form": "8-K", "title": "F-minor", "link": "f1", "important": False},
            {"kind": "filing", "form": "8-K", "title": "F-big", "link": "f2", "important": True},
            {"kind": "headline", "title": "H2", "link": "l2", "tags": ["earnings"]},
            {"kind": "headline", "title": "H3", "link": "l3"},
        ]}
        lines = discord_bot.news_lines(news)
        self.assertTrue(lines[0].startswith("❗ 8-K filing"))
        self.assertIn("F-big", lines[0])
        self.assertEqual(len(lines), 3)                    # 1 filing + 2 headlines
        self.assertIn("(earnings)", lines[2])


class ButtonIdTest(unittest.TestCase):
    def test_ids_carry_action_source_and_signal(self):
        b = discord_bot.DecisionButton("took", "live", 12)
        self.assertEqual(b.item.custom_id, "orb:took:live:12")
        m = re.fullmatch(discord_bot.BUTTON_RE, "orb:skip:replay:7")
        self.assertEqual((m["action"], m["source"], m["sid"]), ("skip", "replay", "7"))
        self.assertIsNone(re.fullmatch(discord_bot.BUTTON_RE, "orb:buy:live:7"))   # no such action
        self.assertEqual(re.fullmatch(discord_bot.BUTTON_RE, "orb:approve:live:9")["action"], "approve")


class PauseTest(unittest.TestCase):
    def test_pause_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "state.json"
            AppState(file=f).paused = True
            self.assertTrue(AppState(file=f).paused)
            AppState(file=f).paused = False
            self.assertFalse(AppState(file=f).paused)


if __name__ == "__main__":
    unittest.main()


class ResolvedAlertTest(unittest.TestCase):
    """#setups: an alert stays a full card only while it needs you; then it collapses."""
    ORIGINAL = "<@123456789> REPLAY · **[ORB] TSLA** breakout · buy $365.75 · stop $358.32 · target $380.61"

    def test_title_drops_the_mention_and_bold(self):
        self.assertEqual(discord_bot.alert_title(self.ORIGINAL),
                         "REPLAY · [ORB] TSLA breakout · buy $365.75 · stop $358.32 · target $380.61")

    def test_skipped_collapses_to_one_small_line_without_the_mention(self):
        c = discord_bot.resolved_content("⏭️ Skipped 10:37 AM", "done", self.ORIGINAL)
        self.assertEqual(c, "-# ⏭️ Skipped 10:37 AM · REPLAY · [ORB] TSLA breakout · buy $365.75 · "
                            "stop $358.32 · target $380.61")
        self.assertNotIn("<@", c)

    def test_open_trade_stays_a_normal_line(self):
        c = discord_bot.resolved_content("🟢 **[ORB] TSLA** · in trade: 6 @ $365.90", "live")
        self.assertEqual(c, "🟢 **[ORB] TSLA** · in trade: 6 @ $365.90")

    def test_finished_trade_collapses(self):
        c = discord_bot.resolved_content("✅ [ORB] TSLA · target hit at $380.61 · +$87.66 · +1.97R", "done")
        self.assertTrue(c.startswith("-# ✅ [ORB] TSLA · target hit"))

    def _msg(self, *buttons):
        from types import SimpleNamespace as NS
        return NS(components=[NS(children=[NS(custom_id=cid, disabled=dis, label=label)
                                           for cid, dis, label in buttons])])

    def test_active_vs_old_locked_alerts(self):
        active = self._msg(("orb:approve:live:1", False, "Approve"), ("orb:skip:live:1", False, "Skip"))
        locked = self._msg(("orb:approve:live:2", True, "✓ Approved"), ("orb:skip:live:2", True, "Skip"))
        self.assertTrue(discord_bot.is_active_alert(active))
        self.assertFalse(discord_bot.is_active_alert(locked))
        self.assertIsNone(discord_bot.chosen_on_old_alert(active))
        self.assertEqual(discord_bot.chosen_on_old_alert(locked), "Approved")
