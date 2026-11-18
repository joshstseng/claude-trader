"""What every strategy bot's brain provides (Step 2b.1).

The plumbing (orders, live cards, the 3:55 sell, restart safety, the trade log, the backtest runner)
is shared by every bot and only talks to a strategy through this contract:

    schedule     when the pre-market step runs and when the checks happen
    watchlist    which stocks to watch today (live) or on a past day (backtest)
    candidates   a cheap pre-filter at each live check (e.g. "closed above its range")
    decide       at a check, for one stock: no trigger yet, or an entry with stop, target and shares
    backtest     when, on a past day, the decision is taken (the last check of the window)

A new strategy subclasses Brain and is listed in app/strategies/__init__.py.
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from pathlib import Path

from app.market import Session


class Brain:
    id: str = ""
    tag: str = ""

    def __init__(self, settings: dict):
        self.s = settings

    # ---------------------------------------------------------------- schedule

    def premarket_at(self, session: Session) -> datetime:
        return session.at(dtime.fromisoformat(self.s["schedule"]["premarket_at"]))

    def check_times(self, session: Session) -> list[datetime]:
        raise NotImplementedError

    # --------------------------------------------------------------- watchlist

    def watchlist_live(self, workdir: Path) -> tuple[list[str], str]:
        """(symbols, one line for the log) for today, built before the open."""
        raise NotImplementedError

    def watchlist_history(self, day, store) -> list[str]:
        """The watchlist this bot would have built on the morning of a past day (no look-ahead)."""
        raise NotImplementedError

    # -------------------------------------------------------------- candidates

    def candidates(self, symbols: list[str], now: str | None, workdir: Path, rules: dict,
                   offline_bars: Path | None = None) -> tuple[list[str], str | None]:
        """(symbols worth a full decision, in the order to handle them; a note if it couldn't run).
        Default: every symbol."""
        return list(symbols), None

    # ------------------------------------------------------------------ decide

    def decide(self, symbol: str, chart: dict, session: Session, now: datetime, rules: dict,
               flat_by: dtime | None = None):
        """-> app.engine.Decision"""
        raise NotImplementedError

    def backtest_check_time(self, session: Session) -> datetime:
        """When a past day's decision is taken: the last live check of the window."""
        return self.check_times(session)[-1]
