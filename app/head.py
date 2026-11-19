"""Step 2b.4: the head bot. It watches the fleet, it doesn't trade.

    python -m app run   with BOT_ROLE=head   (on Railway: its own service, same code)

What it does:
    watchdog        every minute, reads each bot's heartbeat in the shared database; a bot silent for
                    3+ minutes during market hours gets you an @mention in #system (and "back" when it returns)
    fleet summary   once a market day at 4:35 PM ET, one combined line per bot in #daily-summary
    /fleet          every bot: alive?, paused?, today's signals and P&L, open trades and money at risk
    /pause-all      sets the shared global pause (every bot reads it before an alert or an order)
    /resume-all     lifts it (a bot's own /pause stays as it was)
    /flatten-all    global pause + a "flatten" command in the shared database; each bot closes its own
                    account with its own keys and answers; the head reports who did what

The head has no broker keys, and trading never waits on it: if it's down, every bot carries on
(trades stay protected at Alpaca and are still sold at 3:55). The bots watch its heartbeat in turn.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone

from app import costs, market, settings, tradelog

log = logging.getLogger(__name__)
NY = market.NY
HEAD = "head"
STALE_S = 180                 # a trading bot silent this long during market hours -> @mention
HEAD_SILENT_S = 300           # the trading bots' view of the head
RECENT_DAYS = 3               # bots with no heartbeat for longer are treated as retired (not watched)
WATCH_FROM = dtime(9, 0)      # the watchdog's window: 9:00 AM ET to 20 minutes after the close
WATCH_AFTER_CLOSE_MIN = 20
SUMMARY_AT = dtime(16, 35)    # after every bot's own 4:15 PM summary
FLATTEN_WAIT_S = 60
DAY_FMT = "%a %b %d"


# ------------------------------------------------------------------------ settings

@dataclass(frozen=True)
class HeadSettings:
    bot_token: str
    guild_id: int
    owner_id: int
    channel_system: int
    channel_daily_summary: int


def head_settings() -> HeadSettings:
    """The head's own Discord bot (DISCORD_BOT_TOKEN_HEAD), never a trading bot's token: two apps logged in
    as the same Discord bot would wipe each other's slash commands."""
    token = settings._require("DISCORD_BOT_TOKEN_HEAD")
    if token == (os.environ.get("DISCORD_BOT_TOKEN") or "").strip():
        raise settings.SettingsError("DISCORD_BOT_TOKEN_HEAD is the same as DISCORD_BOT_TOKEN. "
                                     "The head bot needs its own Discord bot.")
    return HeadSettings(bot_token=token, guild_id=settings._require_int("DISCORD_GUILD_ID"),
                        owner_id=settings._require_int("DISCORD_OWNER_ID"),
                        channel_system=settings._require_int("DISCORD_CHANNEL_SYSTEM"),
                        channel_daily_summary=settings._require_int("DISCORD_CHANNEL_DAILY_SUMMARY"))


# ------------------------------------------------------------------------ helpers

def bot_name(bot_id: str) -> str:
    return "Head bot" if bot_id == HEAD else f"{bot_id.upper()} bot"


def _when(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def age_s(row, now: datetime) -> float:
    return (now - _when(row["at"])).total_seconds()


def _ago(seconds: float) -> str:
    s = int(max(seconds, 0))
    if s < 90:
        return f"{s}s ago"
    if s < 90 * 60:
        return f"{round(s / 60)} min ago"
    return f"{s / 3600:.1f} h ago"


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def watching(now: datetime, session: market.Session | None) -> bool:
    """Inside the watchdog's window: a market day, 9:00 AM ET to 20 minutes after the close."""
    if session is None:
        return False
    t = now.astimezone(NY)
    return session.at(WATCH_FROM) <= t <= session.at(session.close) + timedelta(minutes=WATCH_AFTER_CLOSE_MIN)


def in_market_hours(now: datetime, session: market.Session | None) -> bool:
    if session is None:
        return False
    t = now.astimezone(NY)
    return session.at(session.open) <= t <= session.at(session.close)


class Watchdog:
    """Remembers who's down so each outage pings once, and says so when the bot is back.

    The head watches every bot but itself (`exclude`); a trading bot watches only the head (`only`)."""

    def __init__(self, *, stale_s: int = STALE_S, only: set[str] | None = None, exclude: set[str] | None = None,
                 down_text=None, back_text=None):
        self.stale_s, self.only, self.exclude = stale_s, only, exclude or set()
        self.down: dict[str, datetime] = {}
        self.down_text = down_text or (lambda bot, age: f"🚨 **{bot_name(bot)} is silent**: no heartbeat since "
                                       f"{_ago(age)}. Check it on Railway. Its open trades stay protected at "
                                       f"Alpaca (stop and target), but it can't sell at 3:55 while it's down.")
        self.back_text = back_text or (lambda bot, gap: f"✅ **{bot_name(bot)} is back** (silent ~{max(1, round(gap / 60))} min).")

    def watched(self, beats, now: datetime) -> list:
        out = []
        for r in beats:
            if r["bot"] in self.exclude or (self.only is not None and r["bot"] not in self.only):
                continue
            if age_s(r, now) > RECENT_DAYS * 86400:
                continue                                  # retired: no heartbeat in days
            out.append(r)
        return out

    def check(self, beats, now: datetime, window: bool) -> list[tuple[str, bool]]:
        """[(message, ping)] to post. Alarms only inside the window; "back" messages any time."""
        msgs = []
        for r in self.watched(beats, now):
            bot, age = r["bot"], age_s(r, now)
            if age > self.stale_s and window and bot not in self.down:
                self.down[bot] = _when(r["at"])
                msgs.append((self.down_text(bot, age), True))
            elif age <= self.stale_s and bot in self.down:
                gap = (_when(r["at"]) - self.down.pop(bot)).total_seconds()
                msgs.append((self.back_text(bot, gap), False))
        return msgs


def head_watchdog() -> Watchdog:
    """For a trading bot: is the head alive? (Only matters during market hours.)"""
    return Watchdog(stale_s=HEAD_SILENT_S, only={HEAD},
                    down_text=lambda bot, age: f"⚠️ **Head bot is silent** (last heard {_ago(age)}). Trading "
                    "carries on as normal; the watchdog, `/pause-all` and `/flatten-all` are offline until it's back. "
                    "This bot's own `/pause` and `/flatten` still work.",
                    back_text=lambda bot, gap: "✅ **Head bot is back.**")


# ------------------------------------------------------------------------ fleet numbers

def fleet_bots(trade_log: tradelog.TradeLog, now: datetime, day: str | None = None) -> list[str]:
    """Every trading bot: heartbeats from the last few days, plus any with live signals on `day`."""
    bots = {r["bot"] for r in trade_log.heartbeats() if r["bot"] != HEAD and age_s(r, now) <= RECENT_DAYS * 86400}
    if day:
        bots |= {r["strategy"] for r in trade_log.db.execute(
            "SELECT DISTINCT strategy FROM signals WHERE source = 'live' AND date = ?", (day,)).fetchall()}
    return sorted(bots)


def bot_numbers(trade_log: tradelog.TradeLog, bot: str, day: str) -> dict:
    sigs = trade_log.db.execute("SELECT COUNT(*) FROM signals WHERE strategy = ? AND source = 'live' AND date = ?",
                                (bot, day)).fetchone()[0]
    alerts = trade_log.db.execute(
        "SELECT COUNT(*) FROM alerts a JOIN signals s ON s.id = a.signal_id WHERE s.strategy = ? AND"
        " s.source = 'live' AND s.date = ? AND a.sent = 1", (bot, day)).fetchone()[0]
    today = costs.paper_trades(trade_log, day, strategy=bot)
    every = costs.running(costs.paper_trades(trade_log, strategy=bot))
    closed = [t for t in today if t["closed"]]
    risk = 0.0
    open_ = trade_log.open_orders(strategy=bot)
    for o in open_:
        price = o["filled_price"] if o["filled_qty"] else o["limit_price"]
        qty = o["filled_qty"] or o["qty"]
        if price is not None and o["stop"] is not None:
            risk += max(price - o["stop"], 0) * qty
    return {"bot": bot, "signals": int(sigs), "alerts": int(alerts),
            "orders": sum(1 for t in today if t["status"] != "rejected"),
            "filled": sum(1 for t in today if t["filled_qty"]), "closed": len(closed),
            "wins": sum(1 for t in closed if (t["pnl_usd"] or 0) > 0),
            "day_pnl": sum(t["pnl_usd"] or 0 for t in closed), "all_time": every["total"],
            "all_trades": every["trades"], "open": len(open_), "at_risk": risk}


def summary_text(nums: list[dict], day: str, paused: bool) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    lines = [f"🧭 **Fleet · {d:{DAY_FMT}}**" + (" · ⏸️ global pause is **on**" if paused else "")]
    if not nums:
        lines.append("No trading bots reported today.")
    for n in nums:
        trades = (f"{n['closed']} closed ({n['wins']} won) · **{_usd(n['day_pnl'])}**" if n["closed"]
                  else "no closed trades")
        lines.append(f"**{bot_name(n['bot'])}** · {n['signals']} signals · {n['alerts']} alerts · "
                     f"{n['orders']} orders · {trades} · all-time {_usd(n['all_time'])}"
                     + (f" · ⚠️ {n['open']} still open" if n["open"] else ""))
    if len(nums) > 1:
        lines.append(f"**Fleet today {_usd(sum(n['day_pnl'] for n in nums))}** · all-time "
                     f"{_usd(sum(n['all_time'] for n in nums))}")
    return "\n".join(lines)


def status_text(trade_log: tradelog.TradeLog, now: datetime, session: market.Session | None) -> str:
    day = now.astimezone(NY).strftime("%Y-%m-%d")
    beats = {r["bot"]: r for r in trade_log.heartbeats()}
    paused = trade_log.global_pause()
    lines = ["🧭 **Fleet**" + (" · ⏸️ **global pause on** (`/resume-all`)" if paused else " · global pause off")]
    lines.append("Market closed today." if session is None else
                 f"Market today {session.open:%-I:%M %p}–{session.close:%-I:%M %p} ET"
                 + (" (early close)" if session.early_close else ""))
    total_risk = 0.0
    for bot in fleet_bots(trade_log, now, day):
        b = beats.get(bot)
        if b is None:
            alive = "⚪ no heartbeat yet"
        else:
            a = age_s(b, now)
            alive = (f"🟢 {b['note'] or 'running'}" if a <= STALE_S else "🔴 silent") + f" · heard {_ago(a)}"
        n = bot_numbers(trade_log, bot, day)
        total_risk += n["at_risk"]
        lines.append(f"**{bot_name(bot)}** {alive}\n"
                     f"  today: {n['signals']} signals · {n['alerts']} alerts · {n['orders']} orders · "
                     f"closed {_usd(n['day_pnl'])} · open {n['open']} (at risk ${n['at_risk']:,.2f})")
    lines.append(f"**Money at risk across bots: ${total_risk:,.2f}** (loss if every open trade hit its stop)")
    return "\n".join(lines)[:1990]


def flatten_report(acks: list, expected: list[str]) -> str:
    done = {a["bot"]: a for a in acks}
    lines = ["🛑 **/flatten-all** · ⏸️ global pause **on** (`/resume-all` to allow trading again)"]
    for bot in sorted(set(expected) | set(done)):
        if bot in done:
            lines.append(f"✅ **{bot_name(bot)}**: {done[bot]['result'] or 'done'}")
        else:
            lines.append(f"⚠️ **{bot_name(bot)}**: no answer. Use its own `/flatten confirm:yes`, or check Alpaca.")
    if not expected and not done:
        lines.append("No trading bot is alive to flatten.")
    return "\n".join(lines)


# ------------------------------------------------------------------------ the Discord bot

def make_head_bot(cfg: HeadSettings, trade_log: tradelog.TradeLog, calendar):
    import discord
    from discord import app_commands

    class _HeadBot(discord.Client):
        def __init__(self):
            super().__init__(intents=discord.Intents.default())
            self.cfg, self.log, self.calendar = cfg, trade_log, calendar
            self.tree = app_commands.CommandTree(self)
            self.ready = asyncio.Event()
            self.watchdog = Watchdog(exclude={HEAD})
            self._last_error_post = 0.0
            self._add_commands()

        async def setup_hook(self) -> None:
            guild = discord.Object(id=cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

        async def on_ready(self) -> None:
            log.info("Discord: logged in as %s", self.user)
            self.ready.set()

        def session(self, now: datetime):
            return self.calendar.session(now.astimezone(NY).date())

        async def post(self, channel_id: int, text: str, *, ping: bool = False) -> None:
            await self.ready.wait()
            ch = self.get_channel(channel_id)
            if ch is None:
                raise RuntimeError(f"channel {channel_id} not found (check the channel ids)")
            await ch.send((f"<@{cfg.owner_id}> " if ping else "") + text[:1900])

        def post_error_threadsafe(self, text: str) -> None:
            now = time.monotonic()
            if now - self._last_error_post < 60 or self.loop is None or self.is_closed():
                return
            self._last_error_post = now
            asyncio.run_coroutine_threadsafe(self.post(cfg.channel_system, f"⚠️ {text}", ping=True), self.loop)

        # ---- every minute

        async def tick(self) -> None:
            now = datetime.now(timezone.utc)
            await asyncio.to_thread(self.log.beat, HEAD, "watching")
            session = self.session(now)
            beats = await asyncio.to_thread(self.log.heartbeats)
            for text, ping in self.watchdog.check(beats, now, watching(now, session)):
                await self.post(cfg.channel_system, text, ping=ping)
            await self.summary_if_due(now, session)

        async def summary_if_due(self, now: datetime, session) -> bool:
            et = now.astimezone(NY)
            day = et.strftime("%Y-%m-%d")
            if session is None or et < session.at(SUMMARY_AT):
                return False
            if await asyncio.to_thread(self.log.fleet, "head_summary_day") == day:
                return False
            text = await asyncio.to_thread(self.summary, now, day)
            await self.post(cfg.channel_daily_summary, text)
            await asyncio.to_thread(self.log.set_fleet, "head_summary_day", day)
            return True

        def summary(self, now: datetime, day: str) -> str:
            nums = [bot_numbers(self.log, b, day) for b in fleet_bots(self.log, now, day)]
            return summary_text(nums, day, self.log.global_pause())

        async def run_loop(self) -> None:
            while True:
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001 - keep watching
                    log.exception("head bot tick failed")
                await asyncio.sleep(60)

        # ---- slash commands (owner only)

        def _add_commands(self) -> None:
            tree = self.tree
            owner = app_commands.check(lambda i: i.user.id == cfg.owner_id)

            @tree.command(name="fleet", description="Every bot: alive?, paused?, today's trades, money at risk")
            @owner
            async def fleet(interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                now = datetime.now(timezone.utc)
                text = await asyncio.to_thread(status_text, self.log, now, self.session(now))
                await interaction.followup.send(text, ephemeral=True)

            @tree.command(name="pause-all", description="Pause EVERY bot: no new alerts or orders (open trades stay protected)")
            @owner
            async def pause_all(interaction: discord.Interaction):
                await asyncio.to_thread(self.log.set_fleet, "global_pause", "on")
                await interaction.response.send_message(
                    "⏸️ **Global pause on**: no bot sends alerts or places orders until `/resume-all`. "
                    "Open trades keep their stop and target and are still sold at 3:55.")

            @tree.command(name="resume-all", description="Lift the global pause (each bot's own /pause stays as it is)")
            @owner
            async def resume_all(interaction: discord.Interaction):
                await asyncio.to_thread(self.log.set_fleet, "global_pause", "off")
                await interaction.response.send_message(
                    "▶️ **Global pause off**: bots trade again (a bot paused with its own `/pause` stays paused).")

            @tree.command(name="flatten-all", description="KILL SWITCH for every bot: close everything, then pause all")
            @app_commands.describe(confirm='type "yes" to close every bot\'s positions now')
            @owner
            async def flatten_all(interaction: discord.Interaction, confirm: str):
                if confirm.strip().lower() != "yes":
                    await interaction.response.send_message(
                        "Nothing done. Type `/flatten-all confirm:yes` to close every bot's positions.", ephemeral=True)
                    return
                await interaction.response.defer()
                text = await self.flatten_all(str(interaction.user.id))
                await interaction.followup.send(text)

            @tree.error
            async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
                if isinstance(error, app_commands.CheckFailure):
                    await interaction.response.send_message("Only the owner can do that.", ephemeral=True)
                else:
                    log.exception("slash command failed", exc_info=error)

        async def flatten_all(self, by: str, wait_s: float = FLATTEN_WAIT_S, poll_s: float = 2.0) -> str:
            await asyncio.to_thread(self.log.set_fleet, "global_pause", "on")
            cmd = await asyncio.to_thread(self.log.add_command, "flatten", by)
            now = datetime.now(timezone.utc)
            beats = await asyncio.to_thread(self.log.heartbeats)
            expected = [r["bot"] for r in beats if r["bot"] != HEAD and age_s(r, now) <= STALE_S]
            deadline = time.monotonic() + wait_s
            while True:
                acks = await asyncio.to_thread(self.log.command_acks, cmd)
                if set(expected) <= {a["bot"] for a in acks} or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(poll_s)
            return flatten_report(acks, expected)

    return _HeadBot()


# ------------------------------------------------------------------------ running it

async def _live(cfg: HeadSettings, trade_log: tradelog.TradeLog) -> None:
    from app.discord_bot import DiscordErrorHandler
    bot = make_head_bot(cfg, trade_log, market.SkillCalendar())
    logging.getLogger().addHandler(DiscordErrorHandler(bot))
    loop = asyncio.get_running_loop()
    me = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, me.cancel)
    async with bot:
        bot_task = asyncio.create_task(bot.start(cfg.bot_token))
        ready = asyncio.create_task(bot.ready.wait())
        await asyncio.wait({bot_task, ready}, return_when=asyncio.FIRST_COMPLETED)
        if bot_task.done():
            bot_task.result()
        now = datetime.now(timezone.utc)
        bots = await asyncio.to_thread(fleet_bots, trade_log, now)
        await bot.post(cfg.channel_system, "🧭 **Head bot online** · watching: "
                       + (", ".join(bot_name(b) for b in bots) or "no bots yet")
                       + (" · ⏸️ global pause is **on**" if await asyncio.to_thread(trade_log.global_pause) else ""))
        loop_task = asyncio.create_task(bot.run_loop())
        try:
            await bot_task
        except asyncio.CancelledError:
            log.info("Stopping")
            try:
                await asyncio.wait_for(bot.post(cfg.channel_system, "🔴 **Head bot stopped.** The trading bots "
                                                "carry on; no watchdog until it's back."), 10)
            except Exception:  # noqa: BLE001
                pass
        finally:
            loop_task.cancel()


def run() -> int:
    from app import logs
    from app.__main__ import single_instance
    lock = single_instance()  # noqa: F841 - held until exit
    logs.setup()
    if not tradelog.database_url():
        raise settings.SettingsError("The head bot needs DATABASE_URL (the shared Postgres): it reads every bot from it.")
    cfg = head_settings()
    trade_log = tradelog.TradeLog()
    try:
        asyncio.run(_live(cfg, trade_log))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    log.info("Stopped")
    return 0
