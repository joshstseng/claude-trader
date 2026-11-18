"""Runs the ORB bot's day on a clock: pre-market at 8:30, checks every 5 minutes in the scan window,
after-close at 4:15 PM. The same code runs live (real clock) and replays (simulated clock).

Heavy work (scripts, downloads) runs in a worker thread so the Discord bot stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Awaitable, Callable

from app import market
from app.routine import OrbDay
from app.state import AppState

log = logging.getLogger(__name__)
NY = market.NY
Notify = Callable[[str], Awaitable[None]]
PREMARKET_TRIES, PREMARKET_RETRY_S = 3, 120
BACKUP_AFTER_MIN = 3


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


async def _say(notify: Notify | None, text: str) -> None:
    if notify:
        try:
            await notify(text)
        except Exception:  # noqa: BLE001 - a failed message never stops the day
            log.exception("could not post: %s", text)


async def run_day(day_bot: OrbDay, session: market.Session, clock, *, simulated: bool,
                  focus: list[str] | None = None, state: AppState | None = None,
                  notify: Notify | None = None,
                  after_close: Callable[[OrbDay], Awaitable[None]] | None = None,
                  flatten: Callable[[OrbDay, str], Awaitable[None]] | None = None) -> None:
    """One trading day. Checks whose time has passed are skipped (a later check catches up).
    If the app starts after the scan window, the focus list isn't built at all."""
    s = day_bot.s
    as_arg = (lambda t: t.strftime("%Y-%m-%d %H:%M")) if simulated else (lambda t: None)
    times = [t for t in market.check_times(session, s) if clock.now() <= t + timedelta(minutes=2)]
    day_bot.session = session
    if state:
        state.day, state.session = day_bot, session

    if times:
        pre = session.at(_hhmm(s["schedule"]["premarket_at"]))
        await clock.sleep_until(pre)
        for attempt in range(1, PREMARKET_TRIES + 1):      # e.g. Yahoo blocking or down: retry, then give up loudly
            try:
                await asyncio.to_thread(day_bot.premarket, focus)
                break
            except Exception:  # noqa: BLE001
                if attempt == PREMARKET_TRIES:
                    log.exception("[ORB] couldn't build today's focus list after %d tries: no checks today",
                                  PREMARKET_TRIES)
                    times = []
                    break
                log.warning("[ORB] focus list failed (try %d), retrying in %ds", attempt, PREMARKET_RETRY_S)
                await asyncio.sleep(0 if simulated else PREMARKET_RETRY_S)
        if times:
            await _say(notify, f"📋 **[ORB]** focus list ready: {len(day_bot.focus)} stocks. Checking every "
                               f"{s['schedule']['check_every_minutes']} min, {times[0]:%-I:%M}–{times[-1]:%-I:%M %p} ET.")
    else:
        log.info("[ORB] started after the scan window; no checks today")

    for t in times:
        if state:
            state.next_check = t
        await clock.sleep_until(t)
        try:
            report = await asyncio.to_thread(day_bot.tick, as_arg(t))
            if state:
                state.last_report = report
        except Exception:                 # noqa: BLE001 - one bad check must not end the day
            log.exception("[ORB] check at %s failed", t.strftime("%H:%M"))
    if state:
        state.next_check = None

    if times:
        sigs = day_bot.log.signals(run_id=day_bot.run_id)
        sent = day_bot.log.alerts_sent(strategy=day_bot.strategy.id, date=day_bot.day, source=day_bot.source,
                                       run_id=day_bot.run_id)
        await _say(notify, f"🏁 **[ORB]** scan window closed: {len(sigs)} signals, {sent} alerts today.")

    # out by the close (1b.6): flatten at 3:55 PM (12:55 on an early close), backup check 3 minutes later
    if flatten is not None and clock.now() < session.at(session.close):
        from app.afterclose import flat_by_for
        flat_at = session.at(flat_by_for(session, day_bot.rules))
        for phase, at in (("flat", flat_at), ("backup", flat_at + timedelta(minutes=BACKUP_AFTER_MIN))):
            await clock.sleep_until(at)
            try:
                await flatten(day_bot, phase)
            except Exception:  # noqa: BLE001 - logged as an error: pings you
                log.exception("[ORB] flatten (%s) failed", phase)

    close_at = session.at(_hhmm(s["schedule"]["after_close_at"]))
    if session.early_close:
        close_at = session.at(session.close) + timedelta(minutes=15)
    await clock.sleep_until(close_at)
    if after_close:
        await after_close(day_bot)
    day_bot.finish()


async def run_forever(make_day: Callable[[str], OrbDay], calendar, clock: RealClock, *,
                      state: AppState | None = None, notify: Notify | None = None, after_close=None, flatten=None,
                      catch_up: Callable[[str, market.Session], Awaitable[None]] | None = None):
    """Live: run every market day, sleep through nights, weekends and holidays.
    `catch_up` runs when the app starts after today's close (e.g. it was down at 4:15 PM), so the
    day's results still get worked out."""
    while True:
        now = clock.now()
        session = await asyncio.to_thread(calendar.session, now.date())
        if state:
            state.session, state.day = session, None
        if session and now < session.at(session.close):
            day_bot = make_day(now.date().isoformat())
            await run_day(day_bot, session, clock, simulated=False, state=state, notify=notify,
                          after_close=after_close, flatten=flatten)
        elif session and catch_up:
            try:
                await catch_up(now.date().isoformat(), session)
            except Exception:  # noqa: BLE001
                log.exception("[ORB] after-close catch-up failed")
        elif session is None and now.weekday() < 5:
            await _say(notify, f"🏖️ Market closed today ({now:%a %b %-d}). See you next market day.")
        tomorrow = datetime.combine(now.date() + timedelta(days=1), dtime(7, 0), tzinfo=NY)
        log.info("Sleeping until %s", tomorrow.strftime("%a %Y-%m-%d %H:%M"))
        await clock.sleep_until(tomorrow)
