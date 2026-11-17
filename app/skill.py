"""day-trader-skill's scripts loaded as modules, so the backtest calls the exact same rules the live
bot runs (entry.evaluate, exit.compute, size.size_trade, scan.find_setups). Never edited."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from types import ModuleType

from app import paths

FILES = {
    "scan": paths.SKILL_DIR / "trader-scanner" / "scan.py",
    "entry": paths.SKILL_DIR / "trader-entry" / "entry.py",
    "exit": paths.SKILL_DIR / "trader-exit" / "exit.py",
    "size": paths.SKILL_DIR / "trader-budget" / "size.py",
}


@lru_cache(maxsize=None)
def module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"dts_{name}", FILES[name])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
