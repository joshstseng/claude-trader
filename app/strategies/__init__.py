"""Strategy bots. Each has an id (e.g. "orb") that tags every log row, alert and backtest run, and a
brain (app/strategies/<id>.py, see base.py for the contract).

To add a bot: write its brain, put its settings in config/strategies/<id>.json and list it in BRAINS.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from app import paths
from app.settings import SettingsError, _read_json

# id -> "module:Class" of its brain (imported only when needed)
BRAINS = {
    "orb": "app.strategies.orb:OrbBrain",
    "demo": "app.strategies.demo:DemoBrain",
}
KNOWN = tuple(BRAINS)


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    enabled: bool
    settings: dict   # the full JSON, so a backtest can snapshot exactly what ran

    @property
    def brain(self):
        return brain_for(self.settings)

    @property
    def tag(self) -> str:
        return tag_for(self.id)


def brain_for(settings: dict):
    """The brain for a strategy's settings (its "id" says which)."""
    sid = settings.get("id", "orb")
    if sid not in BRAINS:
        raise SettingsError(f"Unknown strategy {sid!r}. Known: {', '.join(KNOWN)}")
    module, cls = BRAINS[sid].split(":")
    return getattr(importlib.import_module(module), cls)(settings)


def tag_for(strategy_id: str) -> str:
    """'orb' -> 'ORB' (the brain's tag), as shown in [ORB] on every message."""
    if strategy_id in BRAINS:
        module, cls = BRAINS[strategy_id].split(":")
        return getattr(importlib.import_module(module), cls).tag or strategy_id.upper()
    return strategy_id.upper()


# The bot this process runs (one bot per process). Messages and logs use its tag.
_active = {"id": "orb"}


def set_active(strategy_id: str) -> None:
    if strategy_id not in BRAINS:
        raise SettingsError(f"Unknown strategy {strategy_id!r}. Known: {', '.join(KNOWN)}")
    _active["id"] = strategy_id


def active_id() -> str:
    return _active["id"]


def tag() -> str:
    """The running bot's tag, e.g. ORB."""
    return tag_for(_active["id"])


def load(strategy_id: str, config_dir: Path = paths.STRATEGY_CONFIG_DIR) -> Strategy:
    if strategy_id not in KNOWN:
        raise SettingsError(f"Unknown strategy {strategy_id!r}. Known: {', '.join(KNOWN)}")
    data = _read_json(config_dir / f"{strategy_id}.json")
    if data.get("id") != strategy_id:
        raise SettingsError(
            f"config/strategies/{strategy_id}.json has id {data.get('id')!r}, expected {strategy_id!r}"
        )
    return Strategy(id=strategy_id, name=data.get("name", strategy_id),
                    enabled=bool(data.get("enabled", False)), settings=data)


def load_enabled(config_dir: Path = paths.STRATEGY_CONFIG_DIR) -> list[Strategy]:
    return [s for s in (load(i, config_dir) for i in KNOWN) if s.enabled]
