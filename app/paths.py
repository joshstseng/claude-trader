"""Where things live.

Code and settings are in the repo. Everything the app writes goes under one storage folder: the repo
by default, or TRADER_STORAGE (e.g. /data, a Railway volume) so it survives redeploys.

Step 2b.2: storage is per bot. The bot is STRATEGY (default "orb").
    the ORB bot          keeps the original layout: <storage>/data, <storage>/runs, <storage>/logs
    any other bot <id>   gets its own: <storage>/bots/<id>/data, …/runs, …/logs
So two bots can never touch each other's trade log, day account, pause setting, cards or lock, even
if they share a disk. Shared by every bot: SHARED_DATA_DIR (market data cache, the stock list, and
backtest runs and reports, which are tagged by strategy).
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "day-trader-skill"   # vendored, never edited
CONFIG_DIR = REPO_ROOT / "config"
STRATEGY_CONFIG_DIR = CONFIG_DIR / "strategies"
ENV_FILE = REPO_ROOT / ".env"

STORAGE_DIR = Path(os.environ.get("TRADER_STORAGE") or REPO_ROOT).resolve()
SHARED_DATA_DIR = STORAGE_DIR / "data"       # bars cache, stock list, backtests (all bots)


def bot_dir(bot_id: str) -> Path:
    """A bot's own storage folder (the ORB bot keeps the original layout)."""
    return STORAGE_DIR if bot_id == "orb" else STORAGE_DIR / "bots" / bot_id


# Step 2b.4: BOT_ROLE=head makes this process the head bot (its own folder: bots/head/)
IS_HEAD = (os.environ.get("BOT_ROLE") or "").strip().lower() == "head"
BOT_ID = "head" if IS_HEAD else (os.environ.get("STRATEGY") or "orb").strip().lower() or "orb"
BOT_DIR = bot_dir(BOT_ID)
DATA_DIR = BOT_DIR / "data"                  # this bot's trade log (SQLite), pause setting, lock
RUNS_DIR = BOT_DIR / "runs"                  # one folder per signal: runs/<date>/<strategy>/<TICKER>/
LOGS_DIR = BOT_DIR / "logs"
