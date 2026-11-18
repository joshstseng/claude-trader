"""Step 2b.2: storage is per bot. The ORB bot keeps the original layout; any other bot is separate."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import paths

REPO = Path(__file__).resolve().parent.parent


def layout(storage: str, strategy: str | None) -> dict:
    """The paths a fresh process would use (paths are fixed when the app starts)."""
    env = {k: v for k, v in os.environ.items() if k not in ("STRATEGY", "TRADER_STORAGE")}
    env["TRADER_STORAGE"] = storage
    if strategy is not None:
        env["STRATEGY"] = strategy
    code = ("import json; from app import paths, strategies; from app.state import STATE_FILE; "
            "from app.tradelog import DEFAULT_DB; from app.market import SCANNER_DIR; "
            "from app.backtest import data, run; "
            "print(json.dumps({'data': str(paths.DATA_DIR), 'runs': str(paths.RUNS_DIR), 'logs': str(paths.LOGS_DIR), "
            "'tradelog': str(DEFAULT_DB), 'pause': str(STATE_FILE), 'bars': str(data.CACHE), "
            "'stocks': str(SCANNER_DIR), 'backtests': str(run.DB), 'tag': strategies.tag()}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


class BotStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = str(Path(self.tmp.name).resolve())

    def tearDown(self):
        self.tmp.cleanup()

    def test_orb_keeps_the_original_layout(self):
        """What the live ORB bot on Railway has always used (/data/data/tradelog.db, …)."""
        for strategy in (None, "orb"):
            L = layout(self.s, strategy)
            self.assertEqual(L["tradelog"], f"{self.s}/data/tradelog.db")
            self.assertEqual(L["pause"], f"{self.s}/data/state.json")
            self.assertEqual((L["runs"], L["logs"]), (f"{self.s}/runs", f"{self.s}/logs"))
            self.assertEqual(L["tag"], "ORB")

    def test_another_bot_has_its_own_folder(self):
        L = layout(self.s, "demo")
        self.assertEqual(L["tradelog"], f"{self.s}/bots/demo/data/tradelog.db")
        self.assertEqual(L["pause"], f"{self.s}/bots/demo/data/state.json")
        self.assertEqual((L["runs"], L["logs"]), (f"{self.s}/bots/demo/runs", f"{self.s}/bots/demo/logs"))
        self.assertEqual(L["tag"], "DEMO")

    def test_market_data_and_backtests_are_shared(self):
        orb, demo = layout(self.s, "orb"), layout(self.s, "demo")
        for k in ("bars", "stocks", "backtests"):
            self.assertEqual(orb[k], demo[k])
        self.assertEqual(orb["bars"], f"{self.s}/data/bars")

    def test_bot_dir(self):
        self.assertEqual(paths.bot_dir("orb"), paths.STORAGE_DIR)
        self.assertEqual(paths.bot_dir("vwap"), paths.STORAGE_DIR / "bots" / "vwap")


if __name__ == "__main__":
    unittest.main()
