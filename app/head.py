"""Step 2b.4: the head bot. It watches the fleet, it doesn't trade.

    python -m app run   with BOT_ROLE=head   (on Railway: its own service, same code)

What it does:
    watchdog        every minute, reads each bot's heartbeat in the shared database; a bot silent for
                    3+ minutes during market hours gets you an @mention in #system (and "back" when it returns)
    fleet summary   the only post in #daily-summary: after the close, once every bot has handed in its
                    report (or by 5:00 PM ET), one line per bot, with each bot's full summary in a thread
    /status [bot]   all (default): every bot alive?, paused?, today's numbers, money at risk;
                    a bot's name (e.g. Orbi, Uri): that bot's own status
    /pause-all      sets the shared global pause (every bot reads it before an alert or an order)
    /resume-all     lifts it (a bot's own /pause stays as it was)
    /flatten-all    global pause + a "flatten" command in the shared database; each bot closes its own
                    account with its own keys and answers; the head reports who did what
    #live-trades    while no bot has a trade open, one light "no live trades" message (a new line each
                    time); deleted within seconds of a trade starting, back when it ends
    #closed-trades  after the daily summary, an "unping" command: each bot takes the @mention off its own
                    closed-trade cards for that day (Discord lets a bot edit only its own messages)

The head has no broker keys, and trading never waits on it: if it's down, every bot carries on
(trades stay protected at Alpaca and are still sold at 3:55). The bots watch its heartbeat in turn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone

from app import costs, market, settings, tradelog

log = logging.getLogger(__name__)
NY = market.NY
HEAD = "head"
STALE_S = 180                 # a trading bot silent this long during market hours -> @mention
HEAD_SILENT_S = 300           # the trading bots' view of the head
RECENT_DAYS = 3               # bots with no heartbeat for longer are treated as retired (not watched)
WATCH_FROM = dtime(9, 0)      # the watchdog's window: 9:00 AM ET to 20 minutes after the close
WATCH_AFTER_CLOSE_MIN = 20
SUMMARY_FROM = dtime(16, 15)  # the fleet summary posts once every bot has handed in its report...
SUMMARY_DEADLINE = dtime(17, 0)   # ...or at 5:00 PM ET, naming any bot that didn't
FLATTEN_WAIT_S = 60
DAY_FMT = "%a %b %d"
OWN_LEDGER_BOTS = ("bumi", "swing")     # bots that keep their own trade ledger and publish numbers:<bot>
OVERNIGHT_BOTS = ("bumi",)              # of those, the ones that are meant to hold past the close


# ------------------------------------------------------------------------ settings

@dataclass(frozen=True)
class HeadSettings:
    bot_token: str
    guild_id: int
    owner_id: int
    channel_system: int
    channel_daily_summary: int
    channel_live_trades: int | None = None    # optional: the "no live trades" message


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
                        channel_daily_summary=settings._require_int("DISCORD_CHANNEL_DAILY_SUMMARY"),
                        channel_live_trades=(settings._require_int("DISCORD_CHANNEL_LIVE_TRADES")
                                             if os.environ.get("DISCORD_CHANNEL_LIVE_TRADES", "").strip() else None))


# ------------------------------------------------------------------------ helpers

NAMES: dict[str, str] = {}      # bot id -> its Discord name (from the heartbeats), e.g. orb -> Orbi
INSTANCE = (os.environ.get("RAILWAY_DEPLOYMENT_ID") or f"pid{os.getpid()}")[:12]


def bot_name(bot_id: str) -> str:
    return NAMES.get(bot_id) or ("Head bot" if bot_id == HEAD else f"{bot_id.upper()} bot")


def learn_names(beats) -> None:
    for r in beats:
        try:
            if r["name"]:
                NAMES[r["bot"]] = r["name"]
        except (KeyError, IndexError):
            pass


def find_bot(beats, query: str) -> str | None:
    """'Orbi', 'orb', 'ORB bot', 'Uri', 'head' -> the bot id; 'all' -> 'all'; None if unknown."""
    q = (query or "all").strip().lower()
    if q in ("all", "fleet", "*"):
        return "all"
    for r in beats:
        names = {r["bot"].lower(), bot_name(r["bot"]).lower()}
        try:
            if r["name"]:
                names.add(r["name"].lower())
        except (KeyError, IndexError):
            pass
        if q in names:
            return r["bot"]
    return None


def bot_status_text(trade_log: tradelog.TradeLog, bot: str, now: datetime) -> str:
    """/status <trading bot>: alive?, its own status (as it last reported it), today's numbers."""
    day = now.astimezone(NY).strftime("%Y-%m-%d")
    b = next((r for r in trade_log.heartbeats() if r["bot"] == bot), None)
    if b is None:
        return f"**{bot_name(bot)}**: no heartbeat yet."
    a = age_s(b, now)
    lines = [f"**{bot_name(bot)}** " + (f"🟢 {b['note'] or 'running'}" if a <= STALE_S else "🔴 **silent**")
             + f" · heard {_ago(a)}"]
    status = b["status"] if "status" in b.keys() else None
    if status:
        lines.append(f"-# its own status, as of {_when(b['at']).astimezone(NY):%-I:%M %p} ET:")
        lines.append(status)
    else:
        lines.append("-# (its own status shows here after its next restart)")
    n = bot_numbers(trade_log, bot, day)
    lines.append(f"Today: {n['orders']} orders · closed {_usd(n['day_pnl'])} · open {n['open']} "
                 f"(at risk ${n['at_risk']:,.2f}) · all-time {_usd(n['all_time'])}")
    return "\n".join(lines)[:1990]


def head_status_text(trade_log: tradelog.TradeLog, now: datetime, session, started: datetime | None) -> str:
    """/status <the head>: what the head itself is doing."""
    day = now.astimezone(NY).strftime("%Y-%m-%d")
    bots = fleet_bots(trade_log, now)
    lines = [f"🧭 **{bot_name(HEAD)}** (head bot) 🟢 watching"
             + (f" · online since {started.astimezone(NY):%a %-I:%M %p} ET" if started else "")]
    lines.append("Watching: " + (", ".join(bot_name(b) for b in bots) or "no bots yet")
                 + f" · watchdog {'**on** now' if watching(now, session) else 'off now'} "
                 "(9:00 AM ET to 20 min after the close, market days)")
    lines.append("Global pause: " + ("⏸️ **on** (`/resume-all`)" if trade_log.global_pause() else "off"))
    if session is None:
        lines.append("Market closed today: no daily summary.")
    elif trade_log.fleet(f"head_summary:{day}") or trade_log.fleet("head_summary_day") == day:
        lines.append("Today's summary: ✅ posted")
    else:
        got = {r["bot"] for r in trade_log.reports(day)}
        waiting = [bot_name(b) for b in bots if b not in got]
        lines.append("Today's summary: after 4:15 PM ET, once every bot reports (5:00 PM at the latest)"
                     + (f" · waiting for {', '.join(waiting)}" if waiting and got else ""))
    lines.append(f"-# deploy {INSTANCE}")
    return "\n".join(lines)[:1990]


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


def own_ledger(trade_log: tradelog.TradeLog, bot: str) -> dict:
    try:
        return json.loads(trade_log.fleet(f"numbers:{bot}") or "{}")
    except ValueError:
        return {}


def own_ledger_numbers(trade_log: tradelog.TradeLog, bot: str, day: str) -> dict:
    x, d = own_ledger(trade_log, bot), {}
    d = (x.get("days") or {}).get(day) or {}
    return {"bot": bot, "signals": 0, "alerts": 0, "orders": d.get("orders", 0), "filled": d.get("filled", 0),
            "closed": d.get("closed", 0), "wins": d.get("wins", 0), "day_pnl": d.get("day_pnl", 0.0),
            "all_time": x.get("all_time", 0.0), "all_trades": x.get("all_trades", 0), "open": x.get("open", 0),
            "at_risk": x.get("at_risk", 0.0), "swing": bot in OVERNIGHT_BOTS}


def bot_numbers(trade_log: tradelog.TradeLog, bot: str, day: str) -> dict:
    if bot in OWN_LEDGER_BOTS:
        return own_ledger_numbers(trade_log, bot, day)
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


def chunks(text: str, limit: int = 1900) -> list[str]:
    """Split a long report into Discord-sized messages, on line breaks."""
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def summary_days(now: datetime, calendar, back: int = 7) -> list[tuple[str, bool]]:
    """Days the fleet summary may be due: today once it's past 4:15 PM ET, and the previous market day
    (catch-up if the head was down). [(day, is_today)]"""
    et = now.astimezone(NY)
    out = []
    for i in range(1, back + 1):
        d = et.date() - timedelta(days=i)
        if calendar.session(d) is not None:
            out.append((d.isoformat(), False))
            break
    s = calendar.session(et.date())
    if s is not None and et >= s.at(SUMMARY_FROM):
        out.append((et.date().isoformat(), True))
    return out


def summary_text(nums: list[dict], day: str, paused: bool, missing: list[str] | None = None,
                 details: bool = False) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    def count(x: int, word: str) -> str:
        return f"{x} {word}{'' if x == 1 else 's'}"

    blocks = [f"🧭 **Fleet · {d:{DAY_FMT}}**" + (" · ⏸️ global pause is **on**" if paused else "")]
    if not nums:
        blocks.append("No trading bots reported today.")
    for n in nums:
        result = (f"**{_usd(n['day_pnl'])}** · {n['closed']} closed ({n['wins']} won)" if n["closed"]
                  else "no closed trades")
        held = ((f" · {n['open']} held overnight" if n.get("swing") else f" · ⚠️ {n['open']} still open")
                if n["open"] else "")
        activity = [] if n["bot"] in OWN_LEDGER_BOTS else [count(n["signals"], "signal"), count(n["alerts"], "alert")]
        activity += [count(n["orders"], "order"), f"all-time {_usd(n['all_time'])}"]
        blocks.append(f"**{bot_name(n['bot'])}** · {result}{held}\n-# {' · '.join(activity)}")
    if len(nums) > 1:
        blocks.append(f"**Fleet today {_usd(sum(n['day_pnl'] for n in nums))}** · all-time "
                      f"{_usd(sum(n['all_time'] for n in nums))}")
    for bot in missing or []:
        blocks.append(f"⚠️ No summary from **{bot_name(bot)}** by 5:00 PM ET (check its logs on Railway)")
    if details:
        blocks.append("-# 🧵 Full bot summaries are in the thread")
    return "\n\n".join(blocks)


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

# ------------------------------------------------------------------ #live-trades when it's quiet

IDLE_EVERY_S = 5
IDLE_LINES: dict[str, tuple[str, list[str]]] = {
    "day_off": ("🛋️", [
        "Market's closed. The bots are recharging for next week's hunt.",
        "Day off. Even the best traders sharpen the axe before swinging it.",
        "No market today. The bots are studying the tape and dreaming of breakouts.",
        "Weekend mode. Rest now, compound later.",
        "Closed for the day. The next setup is already out there, waiting.",
        "Off day. The bots are doing push-ups and reviewing their stops.",
        "No trading today. Big things start with quiet days like this.",
        "Market's asleep. The bots are polishing their entries for the next open.",
    ]),
    "premarket": ("☕", [
        "Pre-market. Coffee's brewing, charts are loading, the bots are stretching.",
        "Not open yet. The bots are lacing up for the opening bell.",
        "Early hours. Watchlists are warming up and the bots are hungry.",
        "Pre-market quiet. Every great day starts flat.",
        "Calm before the bell. The bots have their game faces on.",
        "Waiting on the open. Somewhere out there is today's best setup.",
        "Pre-market. Stops are set, rules are loaded, nerves are steel.",
        "Not open yet. The bots are reading the room before they walk in.",
    ]),
    "market": ("🔭", [
        "We're chilling, no trades right now. The bots are scouring the market for setups.",
        "No live trades. The bots are out hunting, patient and picky.",
        "Flat and focused. Waiting for a setup worth the risk.",
        "Nothing live. The best trade is sometimes the one you wait for.",
        "Scanning the market. No setup, no trade, no problem.",
        "No position, no stress. The bots have binoculars out.",
        "All quiet on the trading floor. The bots are watching every tick.",
        "Cash is a position too. The bots are waiting for their pitch.",
        "No trades right now. The bots are sniffing out the next breakout.",
        "Patience mode. The market pays the ones who wait for their spot.",
    ]),
    "closed": ("🌙", [
        "Market's closed. Every bot is flat, rested and ready for tomorrow.",
        "Done for the day. The bots are reviewing the tape and plotting tomorrow.",
        "Closing bell rang. Flat, safe and hungry for the next session.",
        "After hours. The bots are cooling down and the stops are all cleared.",
        "Day's done. Tomorrow's setups are already forming.",
        "Market's closed. The bots are counting lessons, not just dollars.",
        "Lights out on the trading floor. See you at the bell.",
        "All flat for the night. Big swings start with a good night's rest.",
    ]),
}


def idle_phase(now: datetime, session: market.Session | None) -> str:
    """day_off (weekend, holiday), premarket, market (open), closed (after the close)."""
    if session is None:
        return "day_off"
    t = now.astimezone(NY).time()
    return "premarket" if t < session.open else "market" if t < session.close else "closed"


def idle_text(phase: str, last: str | None = None, rng: random.Random | None = None) -> tuple[str, str]:
    """(message, line): a line from the phase's list, never the one shown last."""
    emoji, lines = IDLE_LINES[phase]
    line = (rng or random).choice([x for x in lines if x != last] or lines)
    return f"{emoji} **No live trades.** {line}\n-# This clears the moment a trade goes live.", line


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
            self.started = datetime.now(timezone.utc)
            self._last_error_post = 0.0
            self._idle_msg = None          # the "no live trades" message in #live-trades
            self._add_commands()

        async def setup_hook(self) -> None:
            guild = discord.Object(id=cfg.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

        async def on_ready(self) -> None:
            log.info("Discord: logged in as %s", self.user)
            self.ready.set()

        def status_for(self, query: str) -> str:
            now = datetime.now(timezone.utc)
            beats = self.log.heartbeats()
            learn_names(beats)
            which = find_bot(beats, query)
            if which is None:
                known = ", ".join(["all"] + [bot_name(r["bot"]) for r in beats])
                return f"No bot called **{query}**. Try: {known}"
            if which == "all":
                return status_text(self.log, now, self.session(now))
            if which == HEAD:
                return head_status_text(self.log, now, self.session(now), self.started)
            return bot_status_text(self.log, which, now)

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
            await asyncio.to_thread(self.log.beat, HEAD, "watching", name=self.user.name if self.user else None)
            session = self.session(now)
            beats = await asyncio.to_thread(self.log.heartbeats)
            learn_names(beats)
            for text, ping in self.watchdog.check(beats, now, watching(now, session)):
                await self.post(cfg.channel_system, text, ping=ping)
            await self.summary_if_due(now, session)

        async def summary_if_due(self, now: datetime, session=None) -> bool:
            """Post each due day's fleet summary once (remembered in the database)."""
            posted = False
            for day, today in summary_days(now, self.calendar):
                if await asyncio.to_thread(self.already_posted, day):
                    continue
                plan = await asyncio.to_thread(self.summary, now, day, today)
                if plan is None:
                    continue
                text, details = plan
                await self.post_summary(text, details, day)
                await asyncio.to_thread(self.log.set_fleet, f"head_summary:{day}", "posted")
                # each bot takes the @mention off its own closed-trade cards for the day
                await asyncio.to_thread(self.log.add_command, "unping", HEAD, day)
                posted = True
            return posted

        def already_posted(self, day: str) -> bool:
            return bool(self.log.fleet(f"head_summary:{day}")) or self.log.fleet("head_summary_day") == day

        def summary(self, now: datetime, day: str, today: bool):
            """(text, [(bot, report)]) when it's time to post, None while waiting for reports.
            Today: once every bot has reported, or at 5:00 PM ET. A past day (catch-up): only if reports exist."""
            reports = {r["bot"]: r["text"] for r in self.log.reports(day)}
            expected = fleet_bots(self.log, now, day)
            if today:
                deadline = now.astimezone(NY) >= datetime.combine(date.fromisoformat(day), SUMMARY_DEADLINE, tzinfo=NY)
                if not (set(expected) <= set(reports) or deadline):
                    return None
            elif not reports:
                return None
            bots = sorted(set(expected) | set(reports))
            nums = [bot_numbers(self.log, b, day) for b in bots]
            missing = [b for b in bots if b not in reports]
            details = [(b, reports[b]) for b in bots if b in reports]
            return summary_text(nums, day, self.log.global_pause(), missing, details=bool(details)), details

        async def post_summary(self, text: str, details: list[tuple[str, str]], day: str) -> None:
            """The one post in #daily-summary, with each bot's full report in a thread under it."""
            await self.ready.wait()
            ch = self.get_channel(cfg.channel_daily_summary)
            if ch is None:
                raise RuntimeError(f"channel {cfg.channel_daily_summary} not found (check the channel ids)")
            msg = await ch.send(text[:1990])
            if not details:
                return
            target = ch
            try:
                target = await msg.create_thread(name=f"{date.fromisoformat(day):{DAY_FMT}} · each bot's summary",
                                                 auto_archive_duration=1440)
            except discord.HTTPException as e:
                await self.post(cfg.channel_system, "⚠️ Couldn't open the daily summary's thread (the head bot needs "
                                f"**Create Public Threads** and **Send Messages in Threads**): {str(e)[:120]}. "
                                "Posted the details in the channel instead.")
            for bot, report in details:
                for part in chunks(f"**{bot_name(bot)}**\n{report}"):
                    await target.send(part)

        async def run_loop(self) -> None:
            while True:
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001 - keep watching
                    log.exception("head bot tick failed")
                await asyncio.sleep(60)

        # ---- #live-trades when no trade is open

        async def idle_channel(self):
            ch = self.get_channel(cfg.channel_live_trades)
            return ch if ch is not None else await self.fetch_channel(cfg.channel_live_trades)

        async def idle_check(self, now: datetime) -> str | None:
            """Keep one "no live trades" message in #live-trades while no bot has an order open; delete it
            as soon as one does. Returns what it did (posted, edited, deleted) or None."""
            if not cfg.channel_live_trades:
                return None
            if await asyncio.to_thread(self.log.fleet, "head_instance") not in (None, INSTANCE):
                return None                                    # a newer copy of the head owns the message
            busy = bool(await asyncio.to_thread(self.log.open_orders)) or any(
                [(await asyncio.to_thread(own_ledger, self.log, b)).get("open", 0) for b in OWN_LEDGER_BOTS])
            state = json.loads(await asyncio.to_thread(self.log.fleet, "head_idle") or "{}")
            ch = await self.idle_channel()
            if self._idle_msg is None and state.get("msg"):    # after a restart: pick the message back up
                try:
                    self._idle_msg = await ch.fetch_message(int(state["msg"]))
                except discord.NotFound:
                    state = {}
            if busy:
                if self._idle_msg is None and not state:
                    return None
                if self._idle_msg is not None:
                    try:
                        await self._idle_msg.delete()
                    except discord.NotFound:
                        pass
                self._idle_msg = None
                await asyncio.to_thread(self.log.set_fleet, "head_idle", None)
                return "deleted"
            phase = idle_phase(now, self.session(now))
            if self._idle_msg is not None and state.get("phase") == phase:
                return None
            text, line = idle_text(phase, state.get("line"))
            did = None
            if self._idle_msg is not None:
                try:
                    await self._idle_msg.edit(content=text)
                    did = "edited"
                except discord.NotFound:                       # someone deleted it: post a new one
                    pass
            if did is None:
                self._idle_msg, did = await ch.send(text, silent=True), "posted"
            await asyncio.to_thread(self.log.set_fleet, "head_idle",
                                    json.dumps({"msg": str(self._idle_msg.id), "phase": phase, "line": line}))
            return did

        async def idle_loop(self) -> None:
            await self.ready.wait()
            warned = False
            while True:
                try:
                    await self.idle_check(datetime.now(timezone.utc))
                except discord.Forbidden as e:
                    if not warned:
                        warned = True
                        await self.post(cfg.channel_system, "⚠️ Can't post the \"no live trades\" message: the head "
                                        "bot needs **View Channel**, **Send Messages** and **Read Message History** "
                                        f"in #live-trades ({str(e)[:100]}).")
                except Exception:  # noqa: BLE001 - keep going
                    log.warning("live-trades idle message failed", exc_info=True)
                await asyncio.sleep(IDLE_EVERY_S)

        # ---- slash commands (owner only)

        def _add_commands(self) -> None:
            tree = self.tree
            owner = app_commands.check(lambda i: i.user.id == cfg.owner_id)

            @tree.command(name="status", description="A bot's status by name (e.g. Orbi, Uri), or all of them")
            @app_commands.describe(bot="a bot's name, or all (the default)")
            @owner
            async def status(interaction: discord.Interaction, bot: str = "all"):
                await interaction.response.defer(ephemeral=True)
                text = await asyncio.to_thread(self.status_for, bot)
                await interaction.followup.send(text, ephemeral=True)

            @status.autocomplete("bot")
            async def status_bots(interaction: discord.Interaction, current: str):
                try:
                    beats = await asyncio.to_thread(self.log.heartbeats)
                except Exception:  # noqa: BLE001
                    beats = []
                learn_names(beats)
                now = datetime.now(timezone.utc)
                names = ["all"] + [bot_name(r["bot"]) for r in beats if age_s(r, now) <= RECENT_DAYS * 86400]
                return [app_commands.Choice(name=n, value=n) for n in names
                        if current.lower() in n.lower()][:25]

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
        await asyncio.to_thread(trade_log.set_fleet, "head_instance", INSTANCE)   # this copy is the live one
        beats = await asyncio.to_thread(trade_log.heartbeats)
        learn_names(beats)
        NAMES[HEAD] = bot.user.name if bot.user else NAMES.get(HEAD, "Head bot")
        bots = await asyncio.to_thread(fleet_bots, trade_log, now)
        await bot.post(cfg.channel_system, f"🧭 **{bot_name(HEAD)} (head bot) online** · watching: "
                       + (", ".join(bot_name(b) for b in bots) or "no bots yet")
                       + (" · ⏸️ global pause is **on**" if await asyncio.to_thread(trade_log.global_pause) else ""))
        loop_task = asyncio.create_task(bot.run_loop())
        idle_task = asyncio.create_task(bot.idle_loop())
        try:
            await bot_task
        except asyncio.CancelledError:
            log.info("Stopping")
            try:
                replaced = await asyncio.to_thread(trade_log.fleet, "head_instance") not in (None, INSTANCE)
                text = (f"-# 🔄 {bot_name(HEAD)} rebooted with the new deploy"
                        if replaced else f"🔴 **{bot_name(HEAD)} (head bot) stopped.** The trading bots carry on; "
                        "no watchdog until it's back.")
                await asyncio.wait_for(bot.post(cfg.channel_system, text), 10)
            except Exception:  # noqa: BLE001
                pass
        finally:
            loop_task.cancel()
            idle_task.cancel()


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
