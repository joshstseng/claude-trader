"""What the running app knows right now, shared by the scheduler and the Discord bot.

`paused` is saved to data/state.json so a /pause survives a restart.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app import paths

if TYPE_CHECKING:
    from app.market import Session
    from app.routine import OrbDay, TickReport

log = logging.getLogger(__name__)
STATE_FILE = paths.DATA_DIR / "state.json"


@dataclass
class AppState:
    file: Path = STATE_FILE
    started_at: datetime | None = None
    session: "Session | None" = None          # today's market hours (None = closed today)
    day: "OrbDay | None" = None               # today's ORB bot
    next_check: datetime | None = None
    last_report: "TickReport | None" = None
    _paused: bool = field(default=False, repr=False)

    def __post_init__(self):
        try:
            self._paused = bool(json.loads(self.file.read_text()).get("paused", False))
        except (FileNotFoundError, ValueError):
            self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._paused = bool(value)
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps({"paused": self._paused}))
        except OSError as e:
            log.warning("could not save the pause setting: %s", e)
