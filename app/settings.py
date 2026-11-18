"""Loads secrets from .env and rules from config/.

Secrets (keys, tokens, IDs) come from environment variables / .env.
Rules (risk limits, strategy settings) come from JSON files in config/, so
backtests can vary them without touching code.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app import paths


class SettingsError(Exception):
    """A setting is missing or not allowed. The message says which and why."""


@dataclass(frozen=True)
class AlpacaSettings:
    api_key: str
    secret_key: str
    paper: bool


@dataclass(frozen=True)
class DiscordSettings:
    bot_token: str
    guild_id: int
    owner_id: int
    channel_setups: int
    channel_closed_trades: int
    channel_daily_summary: int
    channel_system: int
    channel_live_trades: int | None = None    # Step 1b.9 (optional: without it, no live trade cards)


def load_env(env_file: Path = paths.ENV_FILE) -> None:
    """Read .env into the environment. Real environment variables win."""
    load_dotenv(env_file, override=False)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name} is not set. Fill it in .env (see .env.example).")
    return value


def _require_int(name: str) -> int:
    value = _require(name)
    try:
        return int(value)
    except ValueError:
        raise SettingsError(f"{name} should be a number (a Discord ID), got something else.") from None


def alpaca_settings() -> AlpacaSettings:
    """Alpaca keys. Refuses anything but a paper account (paper only until Step 5)."""
    paper = os.environ.get("ALPACA_PAPER", "true").strip().lower()
    if paper != "true":
        raise SettingsError(
            "ALPACA_PAPER must be true. Live trading is locked until Step 5 of the roadmap."
        )
    return AlpacaSettings(
        api_key=_require("ALPACA_API_KEY"),
        secret_key=_require("ALPACA_SECRET_KEY"),
        paper=True,
    )


def _closed_trades_channel() -> int:
    """#closed-trades. DISCORD_CHANNEL_CLOSED_TRADES; the old name DISCORD_CHANNEL_TRADES still works."""
    if os.environ.get("DISCORD_CHANNEL_CLOSED_TRADES", "").strip():
        return _require_int("DISCORD_CHANNEL_CLOSED_TRADES")
    if os.environ.get("DISCORD_CHANNEL_TRADES", "").strip():
        return _require_int("DISCORD_CHANNEL_TRADES")
    return _require_int("DISCORD_CHANNEL_CLOSED_TRADES")     # neither set: name the new one in the error


def discord_settings() -> DiscordSettings:
    return DiscordSettings(
        bot_token=_require("DISCORD_BOT_TOKEN"),
        guild_id=_require_int("DISCORD_GUILD_ID"),
        owner_id=_require_int("DISCORD_OWNER_ID"),
        channel_setups=_require_int("DISCORD_CHANNEL_SETUPS"),
        channel_closed_trades=_closed_trades_channel(),
        channel_daily_summary=_require_int("DISCORD_CHANNEL_DAILY_SUMMARY"),
        channel_system=_require_int("DISCORD_CHANNEL_SYSTEM"),
        channel_live_trades=(_require_int("DISCORD_CHANNEL_LIVE_TRADES")
                             if os.environ.get("DISCORD_CHANNEL_LIVE_TRADES", "").strip() else None),
    )


def discord_backtests_channel() -> int | None:
    """Optional: #backtests (only needed where backtests run). None = don't post."""
    value = os.environ.get("DISCORD_CHANNEL_BACKTESTS", "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise SettingsError("DISCORD_CHANNEL_BACKTESTS should be a number (a Discord channel ID).") from None


def sec_user_agent() -> str | None:
    """Optional: without it the news step skips SEC filings (the skill says so)."""
    return os.environ.get("SEC_USER_AGENT", "").strip() or None


def _read_json(path: Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise SettingsError(f"Missing settings file: {path}") from None
    except json.JSONDecodeError as e:
        raise SettingsError(f"{path} is not valid JSON: {e}") from None


def risk_rules(config_dir: Path = paths.CONFIG_DIR) -> dict:
    """Shared risk rules, in the same shape as day-trader-skill's trader/config.json."""
    rules = _read_json(config_dir / "risk.json")
    if rules.get("paper") is not True:
        raise SettingsError('config/risk.json must have "paper": true until Step 5 of the roadmap.')
    return rules
