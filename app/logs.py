"""Logging to the terminal and to logs/app.log (rotated, old files deleted automatically)."""

import logging
import logging.handlers
import sys

from app import paths


class BotTag(logging.Filter):
    """Adds the running bot's tag (e.g. ORB) to every log line as %(bot)s."""

    def filter(self, record: logging.LogRecord) -> bool:
        from app.strategies import tag
        record.bot = "HEAD" if paths.IS_HEAD else tag()
        return True


def setup(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_claude_trader", False) for h in root.handlers):
        return
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(bot)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    file = logging.handlers.RotatingFileHandler(paths.LOGS_DIR / "app.log", maxBytes=5_000_000,
                                                backupCount=5)
    term = logging.StreamHandler(sys.stdout)   # stdout: Railway shows stderr lines as errors
    for h in (file, term):
        h.setFormatter(fmt)
        h.addFilter(BotTag())
        h._claude_trader = True
        root.addHandler(h)
    root.setLevel(level)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.ERROR)   # "voice not supported" noise
