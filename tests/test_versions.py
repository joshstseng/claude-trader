"""Deploy check: every bot announces its code version; Uri flags a live bot still on older code."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import head, tradelog

T0 = datetime(2026, 11, 30, 20, 0, tzinfo=timezone.utc)


class Versions(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.log = tradelog.TradeLog(Path(t.name) / "t.db"); self.addCleanup(self.log.close)

    def run_on(self, bot, sha, seen_at=None):
        with mock.patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": sha + "0" * 33, "RAILWAY_GIT_COMMIT_MESSAGE": f"commit {sha}\nbody"}):
            self.log.announce_version(bot)
        if seen_at is not None:
            self.log.set_fleet(f"version_seen:{sha}", seen_at.isoformat())

    def test_first_beat_announces_once(self):
        with mock.patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "abc1234" + "0" * 33}):
            self.log.beat("swing", "running")
            self.log.set_fleet("version:swing", None)
            self.log.beat("swing", "running")                     # not again in the same process
        self.assertIsNone(self.log.fleet("version:swing"))
        self.assertIsNotNone(self.log.fleet("version_seen:abc1234"))

    def test_a_bot_left_behind_is_flagged_after_the_grace_period(self):
        self.run_on("head", "aaaaaaa", T0 - timedelta(hours=5))
        for b in ("swing", "bumi", "orb"):
            self.run_on(b, "bbbbbbb", T0)
        latest, behind = head.version_check(self.log, T0 + timedelta(minutes=5), ["head", "swing", "bumi", "orb"])
        self.assertEqual((latest, behind), ("bbbbbbb", []))      # still inside the 10 minutes
        latest, behind = head.version_check(self.log, T0 + timedelta(minutes=11), ["head", "swing", "bumi", "orb"])
        self.assertEqual((latest, behind), ("bbbbbbb", ["head"]))
        self.assertEqual(json.loads(self.log.fleet("version:head"))["message"], "commit aaaaaaa")

    def test_a_crash_restart_on_old_code_doesnt_look_newer(self):
        self.run_on("swing", "bbbbbbb", T0)
        self.run_on("head", "bbbbbbb")
        self.run_on("orb", "aaaaaaa", T0 - timedelta(days=1))
        self.run_on("orb", "aaaaaaa")                             # restarts later, still the old commit
        latest, behind = head.version_check(self.log, T0 + timedelta(minutes=30), ["swing", "head", "orb"])
        self.assertEqual((latest, behind), ("bbbbbbb", ["orb"]))

    def test_silent_bots_are_ignored(self):
        self.run_on("swing", "bbbbbbb", T0); self.run_on("orb", "aaaaaaa", T0 - timedelta(days=1))
        self.assertEqual(head.version_check(self.log, T0 + timedelta(hours=1), ["swing"]), ("bbbbbbb", []))

    def test_status_shows_each_bots_code(self):
        for b, sha in (("swing", "bbbbbbb"), ("bumi", "aaaaaaa")):
            self.log.beat(b, "running")
        self.run_on("swing", "bbbbbbb", T0); self.run_on("bumi", "aaaaaaa", T0 - timedelta(days=1))
        now = datetime.now(timezone.utc)
        text = head.status_text(self.log, now, None)
        self.assertIn("code `bbbbbbb`", text)
        self.assertIn("code `aaaaaaa` ⚠️ behind", text)


if __name__ == "__main__":
    unittest.main()
