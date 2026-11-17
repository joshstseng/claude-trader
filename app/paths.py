"""Where things live.

Code and settings are in the repo. Everything the app writes (trade log, pause setting, signal
folders, logs) goes under one storage folder: the repo by default, or TRADER_STORAGE (e.g. /data,
a Railway volume) so it survives redeploys.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "day-trader-skill"   # vendored, never edited
CONFIG_DIR = REPO_ROOT / "config"
STRATEGY_CONFIG_DIR = CONFIG_DIR / "strategies"
ENV_FILE = REPO_ROOT / ".env"

STORAGE_DIR = Path(os.environ.get("TRADER_STORAGE") or REPO_ROOT).resolve()
DATA_DIR = STORAGE_DIR / "data"              # trade log (SQLite), pause setting, stock list
RUNS_DIR = STORAGE_DIR / "runs"              # one folder per signal: runs/<date>/<strategy>/<TICKER>/
LOGS_DIR = STORAGE_DIR / "logs"
