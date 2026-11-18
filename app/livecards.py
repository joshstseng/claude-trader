"""#live-trades and #closed-trades (Step 1b.9).

Each paper trade gets ONE card in #live-trades from the moment you Approve:
    ⏳ waiting for fill   [Cancel order]
    🟢 in the trade       [Close now] [Break-even] [Move stop…] [Move target…]
refreshed about every minute (silently) and right away on events. When it ends, the card is deleted
and a final card is posted to #closed-trades with an @mention. Card message ids are saved in the
trade log, so a restart picks the cards back up.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time as dtime

import discord

from app import cards
from app.market import NY
from app.strategies import tag as _tag

log = logging.getLogger(__name__)
TRADE_RE = r"trade:(?P<action>cancel|close|be|stop|target):(?P<cid>[A-Za-z0-9\-]+)"
COLOR = {"waiting": 0xF1C40F, "live": 0x2ECC71, "win": 0x2ECC71, "loss": 0xE74C3C, "flat": 0x95A5A6}


def _link(guild_id: int, channel_id, message_id) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


# ------------------------------------------------------------------- buttons

class TradeButton(discord.ui.DynamicItem[discord.ui.Button], template=TRADE_RE):
    STYLE = {"cancel": ("Cancel order", discord.ButtonStyle.danger),
             "close": ("Close now", discord.ButtonStyle.danger),
             "be": ("Break-even", discord.ButtonStyle.primary),
             "stop": ("Move stop", discord.ButtonStyle.secondary),
             "target": ("Move target", discord.ButtonStyle.secondary)}

    def __init__(self, action: str, cid: str):
        self.action, self.cid = action, cid
        label, style = self.STYLE[action]
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"trade:{action}:{cid}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /):
        return cls(match["action"], match["cid"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from app.discord_bot import owner_only
        return await owner_only(interaction)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await self._handle(interaction)
        except Exception as e:  # noqa: BLE001 - say what went wrong instead of "didn't respond"
            log.exception("trade button %s failed", self.action)
            msg = f"⚠️ That didn't work: {str(e)[:150]}"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    async def _handle(self, interaction: discord.Interaction) -> None:
        lc: LiveCards | None = getattr(interaction.client, "cards", None)
        if lc is None:
            await interaction.response.send_message("Trade management isn't set up in this app.", ephemeral=True)
            return
        row = lc.log.order(self.cid)
        sym = row["symbol"] if row else "?"
        if self.action == "close":
            await interaction.response.send_message(f"Close **{sym}** now at market?", view=ConfirmClose(lc, self.cid),
                                                    ephemeral=True)
            return
        if self.action in ("stop", "target"):
            current = row[self.action] if row else None
            await interaction.response.send_modal(PriceModal(lc, self.cid, self.action, sym, current))
            return
        await interaction.response.defer()               # no reply in #live-trades: the card updates
        fn = lc.manager.cancel if self.action == "cancel" else lc.manager.breakeven
        res = await asyncio.to_thread(fn, self.cid)
        await lc.report(interaction, sym, res)
        await lc.sync(self.cid)


class ConfirmClose(discord.ui.View):
    """The second tap for Close now (30 seconds, then it's gone)."""

    def __init__(self, lc: "LiveCards", cid: str):
        super().__init__(timeout=30)
        self.lc, self.cid = lc, cid

    @discord.ui.button(label="Confirm: close now", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.response.edit_message(content="Closing…", view=None)
        res = await asyncio.to_thread(self.lc.manager.close, self.cid)
        if res.ok:                                       # the card moving + #system say it: no leftover message
            await interaction.delete_original_response()
            row = self.lc.log.order(self.cid)
            await self.lc.bot.post_system(confirmation(row["symbol"] if row else "?", res.message))
        else:
            await interaction.edit_original_response(content="⛔ " + res.message)
        await self.lc.sync(self.cid)

    @discord.ui.button(label="Keep it", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.delete_original_response()     # nothing changed: nothing to leave behind


class PriceModal(discord.ui.Modal):
    def __init__(self, lc: "LiveCards", cid: str, kind: str, sym: str, current):
        super().__init__(title=f"{'Move stop' if kind == 'stop' else 'Move target'}: {sym}")
        self.lc, self.cid, self.kind = lc, cid, kind
        # Discord limits: label <= 45 characters, placeholder <= 100 (it refuses the form otherwise)
        hint = "only up, below the price" if kind == "stop" else "above the current price"
        self.price = discord.ui.TextInput(label=f"New {kind} price"[:45],
                                          placeholder=f"now {cards._m(current)} · {hint}"[:100], max_length=12)
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = float(str(self.price.value).replace("$", "").replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("⛔ That isn't a price.", ephemeral=True)
            return
        await interaction.response.defer()               # no reply in #live-trades: the card updates
        fn = self.lc.manager.move_stop if self.kind == "stop" else self.lc.manager.move_target
        res = await asyncio.to_thread(fn, self.cid, value)
        row = self.lc.log.order(self.cid)
        await self.lc.report(interaction, row["symbol"] if row else "?", res)
        await self.lc.sync(self.cid)


def confirmation(sym: str, message: str) -> str:
    """The #system line for a change you made, e.g. 🔧 [ORB] NET · Stop moved: $287.80 → $300.00 · 2:52 PM ET."""
    return f"🔧 **[{_tag()}] {sym}** · {message.rstrip('.')} · {datetime.now(NY):%-I:%M %p} ET"


def waiting_view(cid: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(TradeButton("cancel", cid))
    return v


def live_view(cid: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for a in ("close", "be", "stop", "target"):
        v.add_item(TradeButton(a, cid))
    return v


# --------------------------------------------------------------------- cards

class LiveCards:
    def __init__(self, bot, trade_log, manager, rules: dict, *, live_channel: int, closed_channel: int,
                 fill_timeout_s: int = 120, session_fn=None):
        self.bot, self.log, self.manager, self.rules = bot, trade_log, manager, rules
        self.live_channel, self.closed_channel = live_channel, closed_channel
        self.timeout, self.session_fn = fill_timeout_s, session_fn
        self._lock = asyncio.Lock()

    async def report(self, interaction: discord.Interaction, sym: str, res) -> None:
        """Done → one line in #system (and the card updates). Refused → a private reply with the reason."""
        if res.ok:
            await self.bot.post_system(confirmation(sym, res.message))
        else:
            await interaction.followup.send("⛔ " + res.message, ephemeral=True)

    def _flat_by(self) -> dtime:
        from app.afterclose import flat_by_for
        return flat_by_for(self.session_fn() if self.session_fn else None, self.rules)

    async def _channel(self, cid: int):
        ch = self.bot.get_channel(cid)
        return ch if ch is not None else await self.bot.fetch_channel(cid)

    async def _live_msg(self, row):
        if not row["live_card_message_id"]:
            return None
        try:
            ch = await self._channel(int(row["live_card_channel_id"] or self.live_channel))
            return await ch.fetch_message(int(row["live_card_message_id"]))
        except (discord.NotFound, discord.Forbidden):
            return None

    def _render(self, row, price=None):
        sig = self.log.signal(row["signal_id"])
        now = datetime.now(NY)
        if row["status"] == "filled":
            title, body, pnl = cards.live_card(row, sig, price, now, self._flat_by(),
                                               self.log.events(row["client_order_id"]))
            color = COLOR["flat"] if pnl is None else COLOR["win"] if pnl >= 0 else COLOR["loss"]
            return discord.Embed(title=title, description=body, color=color), live_view(row["client_order_id"])
        title, body = cards.waiting_card(row, now, self.timeout)
        return discord.Embed(title=title, description=body, color=COLOR["waiting"]), waiting_view(row["client_order_id"])

    async def post(self, cid: str) -> discord.Message | None:
        """A new card for an order (on Approve, or for a trade that doesn't have one yet)."""
        row = self.log.order(cid)
        if row is None:
            return None
        price = await asyncio.to_thread(self.manager.broker.price, row["symbol"]) if row["status"] == "filled" else None
        embed, view = self._render(row, price)
        ch = await self._channel(self.live_channel)
        msg = await ch.send(embed=embed, view=view)
        self.log.update_order(cid, live_card_channel_id=str(ch.id), live_card_message_id=str(msg.id))
        return msg

    def link(self, cid: str) -> str | None:
        row = self.log.order(cid)
        if not row or not row["live_card_message_id"]:
            return None
        return _link(self.bot.cfg.guild_id, row["live_card_channel_id"], row["live_card_message_id"])

    async def sync(self, cid: str, prices: dict | None = None) -> None:
        """Bring one trade's cards up to date with the trade log: refresh, finish or remove."""
        async with self._lock:
            row = self.log.order(cid)
            if row is None:
                return
            if row["status"] == "closed":
                await self._finish(row)
            elif row["status"] in ("cancelled", "rejected", "expired"):
                await self._drop(row, "limit never filled, nothing bought" if row["status"] != "rejected"
                                 else "order rejected by Alpaca")
            else:
                msg = await self._live_msg(row)
                price = None
                if row["status"] == "filled":
                    price = (prices or {}).get(row["symbol"])
                    if price is None:
                        price = await asyncio.to_thread(self.manager.broker.price, row["symbol"])
                embed, view = self._render(row, price)
                if msg is None:
                    ch = await self._channel(self.live_channel)
                    msg = await ch.send(embed=embed, view=view)
                    self.log.update_order(cid, live_card_channel_id=str(ch.id), live_card_message_id=str(msg.id))
                else:
                    await msg.edit(embed=embed, view=view)

    async def sync_signal(self, signal_id: int) -> None:
        row = self.log.order_for_signal(signal_id)
        if row is not None:
            await self.sync(row["client_order_id"])

    async def _finish(self, row) -> None:
        if row["closed_card_message_id"]:
            return                                              # already moved to #closed-trades
        msg = await self._live_msg(row)
        if msg is not None:
            await msg.delete()
        sig = self.log.signal(row["signal_id"])
        head, body = cards.closed_card(row, sig, self.log.events(row["client_order_id"]), self.log.outcome(row["signal_id"]))
        pnl = row["pnl_usd"] or 0
        color = COLOR["win"] if pnl > 0 else COLOR["loss"] if pnl < 0 else COLOR["flat"]
        ch = await self._channel(self.closed_channel)
        out = await ch.send(f"<@{self.bot.cfg.owner_id}> {head}", embed=discord.Embed(description=body, color=color))
        self.log.update_order(row["client_order_id"], closed_card_message_id=str(out.id), live_card_message_id=None)

    async def _drop(self, row, why: str) -> None:
        msg = await self._live_msg(row)
        if msg is None and not row["live_card_message_id"]:
            return
        if msg is not None:
            await msg.delete()
        self.log.update_order(row["client_order_id"], live_card_message_id=None)
        ch = await self._channel(self.closed_channel)
        await ch.send(f"-# ⌛ [{_tag()}] {row['symbol']} · {why}")

    async def ensure_all(self) -> None:
        """Every open trade has a card (e.g. trades from before this feature, or after a restart)."""
        for row in self.log.open_orders():
            if not await self._live_msg(row):
                await self.sync(row["client_order_id"])

    async def refresh_loop(self, every_s: int = 60) -> None:
        while True:
            try:
                rows = self.log.open_orders()
                prices = {}
                if any(r["status"] == "filled" for r in rows):
                    try:
                        prices = {p["symbol"]: p["price"] for p in
                                  await asyncio.to_thread(self.manager.broker.positions) if p["price"]}
                    except Exception:  # noqa: BLE001
                        pass
                for r in rows:
                    await self.sync(r["client_order_id"], prices)
            except Exception:  # noqa: BLE001 - never stop refreshing
                log.warning("live card refresh failed", exc_info=True)
            await asyncio.sleep(every_s)

    async def refresh_closed(self, cid: str) -> None:
        """Re-render a closed card (e.g. after its exit price was corrected), keeping the @mention."""
        row = self.log.order(cid)
        if row is None or not row["closed_card_message_id"]:
            return
        ch = await self._channel(self.closed_channel)
        try:
            msg = await ch.fetch_message(int(row["closed_card_message_id"]))
        except discord.NotFound:
            return
        sig = self.log.signal(row["signal_id"])
        head, body = cards.closed_card(row, sig, self.log.events(cid), self.log.outcome(row["signal_id"]))
        pnl = row["pnl_usd"] or 0
        color = COLOR["win"] if pnl > 0 else COLOR["loss"] if pnl < 0 else COLOR["flat"]
        await msg.edit(content=f"<@{self.bot.cfg.owner_id}> {head}",
                       embed=discord.Embed(description=body, color=color))

    async def add_backtest_lines(self, day: str) -> None:
        """After the 4:15 step: each closed card gets 'Backtest said…'."""
        rows = self.log.db.execute(
            "SELECT o.* FROM orders o JOIN signals s ON s.id = o.signal_id WHERE s.date = ? AND o.status = 'closed'"
            " AND o.closed_card_message_id IS NOT NULL", (day,)).fetchall()
        ch = await self._channel(self.closed_channel)
        for row in rows:
            bt = self.log.outcome(row["signal_id"])
            if bt is None:
                continue
            try:
                msg = await ch.fetch_message(int(row["closed_card_message_id"]))
            except discord.NotFound:
                continue
            if msg.embeds and "Backtest said" not in (msg.embeds[0].description or ""):
                sig = self.log.signal(row["signal_id"])
                _, body = cards.closed_card(row, sig, self.log.events(row["client_order_id"]), bt)
                em = msg.embeds[0].copy()
                em.description = body
                await msg.edit(embed=em)
