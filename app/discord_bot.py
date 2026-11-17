"""The Discord side of the app: alerts in #setups with [Took it] [Skip], slash commands,
and #system messages (online, focus list ready, errors).

The bot runs in the same asyncio loop as the scheduler. The scheduler's checks run in a worker
thread, so DiscordAlerter hands each alert to the bot's loop and waits for the message id.

Only DISCORD_OWNER_ID can press buttons or use commands. Button ids carry the source and the
signal id (e.g. "orb:took:live:12"), so taps still work after a restart, and replay alerts are
recorded in the replay log, never the live one.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any

import discord
from discord import app_commands

from app import paths, tradelog
from app.pipeline import SignalResult
from app.settings import DiscordSettings
from app.state import AppState

log = logging.getLogger(__name__)
NY_FMT = "%-I:%M %p"
DBS = {"live": tradelog.DEFAULT_DB, "replay": paths.DATA_DIR / "replays.db"}
GREEN, GREY, RED = 0x2ECC71, 0x95A5A6, 0xE74C3C


# ----------------------------------------------------------------- formatting

def _money(x: Any) -> str:
    return "-" if x is None else f"${float(x):,.2f}"


def _pct(x: Any) -> str:
    return "-" if x is None else f"{float(x) * 100:.1f}%"


def _et(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        from app.market import NY
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(NY).strftime(NY_FMT)
    except ValueError:
        return ""


def news_lines(news: dict | None, limit: int = 2) -> list[str]:
    """Important 8-K filings first, then the newest headlines."""
    if not news:
        return []
    items = news.get("items") or []
    filings = [i for i in items if i.get("kind") == "filing"]
    heads = [i for i in items if i.get("kind") == "headline"]
    out = []
    for it in sorted(filings, key=lambda i: not i.get("important"))[:1]:
        flag = "❗" if it.get("important") else "📄"
        out.append(f"{flag} {it.get('form', '8-K')} filing {_et(it.get('time'))}: "
                   f"[{(it.get('title') or '')[:90]}]({it.get('link', '')})")
    for it in heads[: limit]:
        tags = f" ({', '.join(it['tags'])})" if it.get("tags") else ""
        out.append(f"• [{(it.get('title') or '')[:100]}]({it.get('link', '')}) {_et(it.get('time'))}{tags}")
    return out


def _clock(hhmm: str | None) -> str:
    """'15:55' -> '3:55 PM'."""
    if not hhmm:
        return "?"
    try:
        return datetime.strptime(hhmm, "%H:%M").strftime(NY_FMT)
    except ValueError:
        return hhmm


def _chg(price: Any, base: Any) -> str:
    if price is None or not base:
        return ""
    return f"{(float(price) / float(base) - 1) * 100:+.1f}%".replace("-", "−")


def plan_block(r: SignalResult) -> str:
    """The numbers in one aligned monospace block (easy to scan on a phone)."""
    plan, order, risk = r.plan or {}, r.order or {}, r.risk or {}
    sizing = (r.data("budget") or {}).get("sizing") or {}
    entry = plan.get("entry")
    cost = sizing.get("cost")
    rows = [
        ("Entry", _money(entry), plan.get("entry_time", "")),
        ("Stop", _money(plan.get("stop")), _chg(plan.get("stop"), entry)),
        ("Target", _money(plan.get("target")),
         f"{_chg(plan.get('target'), entry)}  {plan.get('target_r', '?'):g}R" if plan.get("target_r") else ""),
        ("Size", f"{order.get('qty', '?')} sh", f"${float(cost):,.0f}" if cost else ""),
        ("Risk", _money(risk.get("max_loss")), "if stopped"),
    ]
    return "```\n" + "\n".join(f"{a:<7} {b:<9} {c}".rstrip() for a, b, c in rows) + "\n```"


def alert_message(signal_id: int, source: str, r: SignalResult) -> tuple[str, discord.Embed]:
    """The alert: a one-line preview (what the phone notification shows) plus a compact card."""
    e = r.entry or {}
    trig, orng = e.get("trigger") or {}, e.get("opening_range") or {}
    plan, risk = r.plan or {}, r.risk or {}
    tm = r.data("timemachine") or {}
    mc = tm.get("mc") or {}
    replay = source != "live"
    tag = "REPLAY · " if replay else ""

    preview = (f"{tag}**[ORB] {r.symbol}** breakout · buy {_money(plan.get('entry'))} · "
               f"stop {_money(plan.get('stop'))} · target {_money(plan.get('target'))}")

    lines = []
    if replay:
        try:
            lines.append(f"_Replay of {datetime.strptime(r.date, '%Y-%m-%d'):%a %b %-d, %Y}_")
        except ValueError:
            pass
    vx = trig.get("volume_x")
    lines.append(f"Closed above the 9:30–9:45 high ({_money(orng.get('high'))})"
                 + (f" · volume {vx:g}×" if isinstance(vx, (int, float)) else ""))
    lines.append(plan_block(r))
    if risk.get("verdict") == "PASS":
        lines.append(f"✅ Risk check passed · out by {_clock(plan.get('flat_by'))}")
    else:
        lines.append(f"⛔ Risk check: {risk.get('verdict', '?')} · " + "; ".join(risk.get("reasons", [])))
    if mc:
        verdict = (tm.get("verdict") or "").split(":")[0].strip()
        lines.append(f"🎲 **Odds:** target {_pct(mc.get('p_target'))} · stop {_pct(mc.get('p_stop'))} · "
                     f"neither {_pct(mc.get('p_neither'))}" + (f"\n↳ _{verdict}_" if verdict else ""))
    news = news_lines(r.data("news"))
    if news:
        lines.append("📰 " + "\n".join(n.lstrip("• ") for n in news))

    em = discord.Embed(title=f"{tag}{r.symbol} · ORB breakout", description="\n".join(lines)[:4000],
                       color=GREY if replay else GREEN)
    em.set_footer(text=f"Approve = bracket order on the paper account (entry, stop, target) · #{signal_id}"
                     if not replay else f"Replay: Approve only records · #{signal_id}")
    return preview, em


def with_response(embed: discord.Embed, action: str, when: datetime) -> discord.Embed:
    """The alert after a tap: a 'Your call' line at the bottom. The last tap counts."""
    from app.market import NY
    em = embed.copy()
    desc = (em.description or "").split("\n\n**Your call:**")[0]
    label = {"took": "✅ Took it", "approve": "✅ Approved"}.get(action, "⏭️ Skipped")
    em.description = f"{desc}\n\n**Your call:** {label} · {when.astimezone(NY).strftime(NY_FMT)} ET"
    return em


# --------------------------------------------------------------------- buttons

BUTTON_RE = r"orb:(?P<action>approve|took|skip):(?P<source>live|replay):(?P<sid>[0-9]+)"
LABELS = {"approve": ("Approve", "✓ Approved"), "took": ("Took it", "✓ Took it"), "skip": ("Skip", "✓ Skipped")}


class DecisionButton(discord.ui.DynamicItem[discord.ui.Button], template=BUTTON_RE):
    """[Approve] places a paper bracket order (Step 1b.4); [Skip] records that you passed.
    ("took" only exists on alerts posted before Step 1b: it just records.)"""

    def __init__(self, action: str, source: str, signal_id: int, chosen: str | None = None,
                 locked: bool = False):
        """`chosen` = your last tap (highlighted with a ✓). `locked` = no more taps (an order was
        placed, or the approval was refused for good)."""
        self.action, self.source, self.signal_id = action, source, signal_id
        plain, done = LABELS[action]
        go = action in ("approve", "took")
        if chosen == action:
            label, style = done, (discord.ButtonStyle.success if go else discord.ButtonStyle.primary)
        elif chosen is None and not locked:
            label, style = plain, (discord.ButtonStyle.success if go else discord.ButtonStyle.secondary)
        else:
            label, style = plain, discord.ButtonStyle.secondary
        super().__init__(discord.ui.Button(label=label, style=style, disabled=locked,
                                           custom_id=f"orb:{action}:{source}:{signal_id}"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /):
        return cls(match["action"], match["source"], int(match["sid"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await owner_only(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TraderBot = interaction.client  # type: ignore[assignment]
        trade_log = bot.trade_log(self.source)
        if trade_log.signal(self.signal_id) is None:
            await interaction.response.send_message("I can't find that signal in the log.", ephemeral=True)
            return
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
        now = datetime.now().astimezone()
        if self.action != "approve":                     # Skip (or an old "Took it"): just record it
            trade_log.record_response(self.signal_id, self.action, user_id=interaction.user.id)
            view = decision_view(self.source, self.signal_id, chosen=self.action, kind=self._kind(interaction))
            await interaction.response.edit_message(
                embed=with_response(embed, self.action, now) if embed else discord.utils.MISSING, view=view)
            return

        await interaction.response.defer()               # placing an order can take a few seconds
        if bot.desk is None:
            trade_log.record_response(self.signal_id, "took", user_id=interaction.user.id)
            from app.orders import Outcome
            out = Outcome(False, "📝 Recorded. Ordering isn't set up in this app, so nothing was placed.")
        else:
            out = await asyncio.to_thread(bot.desk.approve, self.signal_id, interaction.user.id,
                                          source=self.source)
        if embed:
            embed = with_order_line(with_response(embed, "approve", now), out.text)
        locked = out.placed or out.final
        await interaction.edit_original_response(
            embed=embed or discord.utils.MISSING,
            view=decision_view(self.source, self.signal_id, chosen="approve" if out.placed else None,
                               locked=locked))
        if out.placed and out.client_id:
            bot.follow_entry(interaction.message, out.client_id)

    @staticmethod
    def _kind(interaction: discord.Interaction) -> str:
        """Keep an old alert's buttons ("Took it") as they were."""
        ids = [c.custom_id for row in (interaction.message.components if interaction.message else [])
               for c in getattr(row, "children", [])]
        return "took" if any(":took:" in (i or "") for i in ids) else "approve"


def decision_view(source: str, signal_id: int, chosen: str | None = None, locked: bool = False,
                  kind: str = "approve") -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DecisionButton(kind, source, signal_id, chosen, locked))
    view.add_item(DecisionButton("skip", source, signal_id, chosen, locked))
    return view


def with_order_line(embed: discord.Embed, text: str) -> discord.Embed:
    """Add an order status line under the alert (each update adds a line, so you see the story)."""
    em = embed.copy()
    desc = em.description or ""
    em.description = (desc + ("\n" if "**Order" in desc or "Not placed" in desc or "Recorded" in desc else "\n\n")
                      + text)[:4000]
    return em


async def owner_only(interaction: discord.Interaction) -> bool:
    bot: TraderBot = interaction.client  # type: ignore[assignment]
    if interaction.user.id == bot.cfg.owner_id:
        return True
    await interaction.response.send_message("Only the owner of this bot can do that.", ephemeral=True)
    return False


# ------------------------------------------------------------------------- bot

class TraderBot(discord.Client):
    def __init__(self, cfg: DiscordSettings, state: AppState):
        super().__init__(intents=discord.Intents.default())
        self.cfg, self.state = cfg, state
        self.tree = app_commands.CommandTree(self)
        self._logs: dict[str, tradelog.TradeLog] = {}
        self.ready = asyncio.Event()
        self._last_error_post = 0.0
        self.desk = None            # app.orders.OrderDesk (live app only): Approve -> paper order
        self._add_commands()

    def trade_log(self, source: str) -> tradelog.TradeLog:
        """The bot's own connection to each log (the scheduler uses another; SQLite WAL handles both)."""
        if source not in self._logs:
            self._logs[source] = tradelog.TradeLog(DBS["live" if source == "live" else "replay"])
        return self._logs[source]

    async def setup_hook(self) -> None:
        self.add_dynamic_items(DecisionButton)
        guild = discord.Object(id=self.cfg.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        log.info("Discord: logged in as %s", self.user)
        self.ready.set()

    # ---- posting

    def channel(self, cid: int) -> discord.abc.Messageable:
        ch = self.get_channel(cid)
        if ch is None:
            raise RuntimeError(f"channel {cid} not found (check .env)")
        return ch

    async def post_system(self, text: str, *, ping: bool = False) -> None:
        await self.ready.wait()
        prefix = f"<@{self.cfg.owner_id}> " if ping else ""
        await self.channel(self.cfg.channel_system).send(prefix + text[:1900])

    async def post_daily(self, text: str) -> None:
        await self.ready.wait()
        await self.channel(self.cfg.channel_daily_summary).send(text)

    async def post_alert(self, signal_id: int, source: str, r: SignalResult) -> tuple[int, int]:
        await self.ready.wait()
        preview, embed = alert_message(signal_id, source, r)
        ch = self.channel(self.cfg.channel_setups)
        msg = await ch.send(preview, embed=embed, view=decision_view(source, signal_id))
        return ch.id, msg.id

    def follow_entry(self, message: discord.Message, client_id: str) -> None:
        """After the fill timeout: filled → say so; not filled → cancelled. Updates the alert."""
        async def follow():
            await asyncio.sleep(int((self.desk.o or {}).get("fill_timeout_seconds", 120)))
            try:
                out = await asyncio.to_thread(self.desk.check_entry, client_id)
                fresh = await message.channel.fetch_message(message.id)
                if fresh.embeds:
                    await fresh.edit(embed=with_order_line(fresh.embeds[0], out.text))
            except Exception:  # noqa: BLE001
                log.exception("[ORB] follow-up for %s failed", client_id)
        asyncio.create_task(follow())

    def post_error_threadsafe(self, text: str) -> None:
        """From any thread; at most one error post a minute so a bad day can't spam you."""
        now = time.monotonic()
        if now - self._last_error_post < 60 or self.loop is None or self.is_closed():
            return
        self._last_error_post = now
        asyncio.run_coroutine_threadsafe(self.post_system(f"⚠️ {text}", ping=True), self.loop)

    # ---- slash commands (owner only)

    def _add_commands(self) -> None:
        tree = self.tree

        @tree.command(name="status", description="Is the ORB bot running? What's it doing today?")
        @app_commands.check(lambda i: i.user.id == self.cfg.owner_id)
        async def status(interaction: discord.Interaction):
            await interaction.response.send_message(self.status_text(), ephemeral=True)

        @tree.command(name="today", description="Today's ORB signals and what happened to each")
        @app_commands.check(lambda i: i.user.id == self.cfg.owner_id)
        async def today(interaction: discord.Interaction):
            await interaction.response.send_message(self.today_text(), ephemeral=True)

        @tree.command(name="pause", description="Stop sending alerts (signals are still logged)")
        @app_commands.check(lambda i: i.user.id == self.cfg.owner_id)
        async def pause(interaction: discord.Interaction):
            self.state.paused = True
            await interaction.response.send_message(
                "⏸️ Paused. Signals are still logged, but no alerts until `/resume`. This stays on after a restart.")

        @tree.command(name="resume", description="Start sending alerts again")
        @app_commands.check(lambda i: i.user.id == self.cfg.owner_id)
        async def resume(interaction: discord.Interaction):
            self.state.paused = False
            await interaction.response.send_message("▶️ Resumed. Alerts are on.")

        @tree.error
        async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message("Only the owner of this bot can do that.",
                                                        ephemeral=True)
            else:
                log.exception("slash command failed", exc_info=error)

    def status_text(self) -> str:
        st = self.state
        lines = [f"**ORB bot** {'⏸️ PAUSED (no alerts)' if st.paused else '🟢 running'} · paper · alerts only"]
        if st.started_at:
            lines.append(f"Online since {st.started_at.strftime('%a %-I:%M %p')} ET")
        if st.session is None:
            lines.append("Market closed today.")
        else:
            s = st.session
            lines.append(f"Market today {s.open:%-I:%M %p}–{s.close:%-I:%M %p} ET"
                         + (" (early close)" if s.early_close else ""))
        if st.day:
            lines.append(f"Focus list: {len(st.day.focus)} stocks")
            day_log = self.trade_log("live")
            sigs = day_log.signals(strategy="orb", source="live", date=st.day.day)
            sent = day_log.alerts_sent(strategy="orb", date=st.day.day)
            lines.append(f"Today: {len(sigs)} signals, {sent} alerts (cap "
                         f"{st.day.s['alerts']['max_per_day']})")
        if st.last_report:
            r = st.last_report
            lines.append(f"Last check {r.at[-5:]} ET: {len(r.candidates)} above range, "
                         f"{len(r.signals)} new signals" + (f" ({r.note})" if r.note else ""))
        if st.next_check:
            lines.append(f"Next check {st.next_check.strftime('%-I:%M %p')} ET")
        return "\n".join(lines)

    def today_text(self) -> str:
        if not self.state.day:
            return "No trading day running right now."
        day = self.state.day.day
        db = self.trade_log("live")
        rows = db.signals(strategy="orb", source="live", date=day)
        if not rows:
            return f"No ORB signals yet on {day}."
        out = [f"**ORB signals {day}**"]
        for r in rows:
            al, resp = db.alert(r["id"]), db.latest_response(r["id"])
            what = "alerted" if al and al["sent"] else f"held: {al['held_reason']}" if al else "?"
            you = f" · you: {resp['action']}" if resp else ""
            out.append(f"`{r['trigger_time']}` **{r['symbol']}** {r['status']} · entry {_money(r['entry'])} "
                       f"stop {_money(r['stop'])} target {_money(r['target'])} · {what}{you}")
        return "\n".join(out)[:1900]


class DiscordAlerter:
    """routine.Alerter that posts to #setups. Called from the scheduler's worker thread."""

    def __init__(self, bot: TraderBot, loop: asyncio.AbstractEventLoop, source: str = "live"):
        self.bot, self.loop, self.source = bot, loop, source

    def send(self, signal_id: int, result: SignalResult):
        fut = asyncio.run_coroutine_threadsafe(self.bot.post_alert(signal_id, self.source, result), self.loop)
        return fut.result(timeout=60)


class DiscordErrorHandler(logging.Handler):
    """Posts ERROR log lines to #system with an @mention (rate limited)."""

    def __init__(self, bot: TraderBot):
        super().__init__(level=logging.ERROR)
        self.bot = bot

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("discord"):
            return   # never loop on Discord's own errors
        try:
            self.bot.post_error_threadsafe(f"Error: {record.getMessage()[:300]} (details in logs/app.log)")
        except Exception:  # noqa: BLE001
            pass


async def post_once(cfg: DiscordSettings, channel_id: int,
                    messages: list[tuple[str, discord.Embed | None, discord.ui.View | None]],
                    files: list | None = None) -> list[int]:
    """Post without connecting to the gateway (replays, backtests). Button taps are handled by the
    running app (`python -m app run`), which knows these button ids. `files` (paths) are attached
    to the last message."""
    client = discord.Client(intents=discord.Intents(guilds=True))
    ids = []
    async with client:
        await client.login(cfg.bot_token)
        ch = await client.fetch_channel(channel_id)
        for i, (content, embed, view) in enumerate(messages):
            kwargs = {"embed": embed} if embed else {}
            if view:
                kwargs["view"] = view
            if files and i == len(messages) - 1:
                kwargs["files"] = [discord.File(str(f)) for f in files]
            ids.append((await ch.send(content, **kwargs)).id)
    return ids
