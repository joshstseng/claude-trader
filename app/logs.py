"""Logging to the terminal and to logs/app.log (rotated, old files deleted automatically)."""

import logging
import logging.handlers

from app import paths


def setup(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_claude_trader", False) for h in root.handlers):
        return
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    file = logging.handlers.RotatingFileHandler(paths.LOGS_DIR / "app.log", maxBytes=5_000_000,
                                                backupCount=5)
    term = logging.StreamHandler()
    for h in (file, term):
        h.setFormatter(fmt)
        h._claude_trader = True
        root.addHandler(h)
    root.setLevel(level)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.ERROR)   # "voice not supported" noise
