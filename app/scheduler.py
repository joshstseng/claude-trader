"""Runs the ORB bot's day on a clock: pre-market at 8:30, checks every 5 minutes in the scan window,
after-close at 4:15 PM. The same code runs live (real clock) and replays (simulated clock).

Heavy work (scripts, downloads) runs in a worker thread so the Discord bot (1a.6) stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Awaitable, Callable

from app import market
from app.routine import OrbDay

log = logging.getLogger(__name__)
NY = market.NY


class RealClock:
    def now(self) -> datetime:
        return datetime.now(NY)

    async def sleep_until(self, t: datetime) -> None:
        # short naps so a Mac that slept wakes up on time instead of after the full remaining sleep
        while (left := (t - self.now()).total_seconds()) > 0:
            await asyncio.sleep(min(left, 30))


class SimClock:
    """Replays: time jumps straight to the next event."""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    async def sleep_until(self, t: datetime) -> None:
        if t > self._now:
            self._now = t


def _hhmm(text: str) -> dtime:
    return dtime.fromisoformat(text)


async def run_day(day_bot: OrbDay, session: market.Session, clock, *, simulated: bool,
                  focus: list[str] | None = None,
                  after_close: Callable[[OrbDay], Awaitable[None]] | None = None) -> None:
    """One trading day. Steps whose time has already passed are skipped, except the focus list,
    which is built right away when the app starts late."""
    s = day_bot.s
    as_arg = (lambda t: t.strftime("%Y-%m-%d %H:%M")) if simulated else (lambda t: None)

    pre = session.at(_hhmm(s["schedule"]["premarket_at"]))
    await clock.sleep_until(pre)
    await asyncio.to_thread(day_bot.premarket, focus)

    for t in market.check_times(session, s):
        if clock.now() > t + timedelta(minutes=2):
            continue                      # missed (app started late); a later check catches up
        await clock.sleep_until(t)
        try:
            await asyncio.to_thread(day_bot.tick, as_arg(t))
        except Exception:                 # noqa: BLE001 - one bad check must not end the day
            log.exception("[ORB] check at %s failed", t.strftime("%H:%M"))

    close_at = session.at(_hhmm(s["schedule"]["after_close_at"]))
    if session.early_close:
        close_at = session.at(session.close) + timedelta(minutes=15)
    await clock.sleep_until(close_at)
    if after_close:
        await after_close(day_bot)
    day_bot.finish()


async def run_forever(make_day: Callable[[str], OrbDay], calendar, clock: RealClock,
                      after_close=None, on_closed_day: Callable[[date], Awaitable[None]] | None = None):
    """Live: run every market day, sleep through nights, weekends and holidays."""
    while True:
        now = clock.now()
        session = calendar.session(now.date())
        if session and now < session.at(session.close):
            day_bot = make_day(now.date().isoformat())
            await run_day(day_bot, session, clock, simulated=False, after_close=after_close)
        elif session is None and on_closed_day:
            await on_closed_day(now.date())
        tomorrow = datetime.combine(now.date() + timedelta(days=1), dtime(7, 0), tzinfo=NY)
        log.info("Sleeping until %s", tomorrow.strftime("%a %Y-%m-%d %H:%M"))
        await clock.sleep_until(tomorrow)
