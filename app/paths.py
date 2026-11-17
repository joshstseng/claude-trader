"""Where things live. Everything is relative to the repo root."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "day-trader-skill"   # vendored, never edited
CONFIG_DIR = REPO_ROOT / "config"
STRATEGY_CONFIG_DIR = CONFIG_DIR / "strategies"
RUNS_DIR = REPO_ROOT / "runs"                # one folder per signal: runs/<date>/<strategy>/<TICKER>/
DATA_DIR = REPO_ROOT / "data"                # trade log (SQLite)
LOGS_DIR = REPO_ROOT / "logs"
ENV_FILE = REPO_ROOT / ".env"
