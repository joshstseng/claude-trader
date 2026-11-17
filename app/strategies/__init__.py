"""Strategy bots. Each has an id (e.g. "orb") that tags every log row, alert and backtest run.

To add a bot later: drop its settings in config/strategies/<id>.json and add its id to KNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app import paths
from app.settings import SettingsError, _read_json

KNOWN = ("orb",)


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    enabled: bool
    settings: dict   # the full JSON, so a backtest can snapshot exactly what ran


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
