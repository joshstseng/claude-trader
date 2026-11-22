"""Bumi's cards: one in #live-trades per open position, refreshed every minute, and one in #closed-trades per exit.
Information only, with no buttons, because Bumi trades without approval. Card ids live in Bumi's state file, so a
restart picks them back up."""

from __future__ import annotations

import inspect
import logging
from datetime import date

import discord

from app import bumi_live as L

log = logging.getLogger(__name__)
GREEN, RED, GREY = 0x2ECC71, 0xE74C3C, 0x95A5A6


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def _pct(a: float, b: float) -> str:
    return f"{(b / a - 1) * 100:+.2f}%".replace("-", "−")


def _day(d: str) -> str:
    return f"{date.fromisoformat(d):%a %b %-d}"


def _held(a: str, b: str) -> str:
    n = (date.fromisoformat(b) - date.fromisoformat(a)).days
    return "same day" if n == 0 else f"{n} day{'' if n == 1 else 's'}"


def live_text(lot: dict, px: float | None, stop: float | None, today: str) -> tuple[str, int]:
    label = "dip trade" if lot["kind"] == "dip" else "calm-market core"
    now = px if px is not None else lot["entry"]
    pnl = (now - lot["entry"]) * lot["qty"]
    lines = [f"🟢 **{lot['sym']}** · {label} · **{_usd(pnl)}** ({_pct(lot['entry'], now)})",
             f"{lot['qty']} sh · in ${lot['entry']:,.2f} on {_day(lot['day_in'])} · "
             + (f"now ${px:,.2f}" if px is not None else "price unavailable")
             + f" · held {_held(lot['day_in'], today)}"]
    if lot["kind"] == "core":
        lines.append("No stop. Sold at the next open once the market stops being calm.")
    elif stop is not None:
        lines.append(f"Stop: {lot['under']} at ${stop:,.2f}. Checked after the close, sold at the next open.")
    else:
        lines.append("Stop updates after today's close.")
    return "\n".join(lines), GREEN if pnl >= 0 else RED


def closed_text(t: dict) -> tuple[str, int]:
    icon = "✅" if t["pnl"] > 0 else "❌" if t["pnl"] < 0 else "➖"
    label = "dip trade" if t["kind"] == "dip" else "calm-market core"
    body = (f"{icon} **{t['sym']}** · {label} · **{_usd(t['pnl'])}** ({_pct(t['entry'], t['exit'])})\n"
            f"In ${t['entry']:,.2f} ({_day(t['day_in'])}) → out ${t['exit']:,.2f} ({_day(t['day_out'])}) · "
            f"{t['qty']} sh · held {_held(t['day_in'], t['day_out'])}\nExit: {t['why']}")
    return body, GREEN if t["pnl"] > 0 else RED if t["pnl"] < 0 else GREY


class BumiCards:
    def __init__(self, state: L.State, broker, channel, live_channel: int | None, closed_channel: int):
        self.state, self.broker, self.channel = state, broker, channel
        self.live_id, self.closed_id = live_channel, closed_channel

    async def _ch(self, cid: int):
        c = self.channel(cid)
        return await c if inspect.isawaitable(c) else c

    async def sync(self, today: str) -> None:
        import asyncio
        led = self.state.ledger
        for t in led["closed"]:
            if t["card_posted"]:
                continue
            if t.get("live_card") and self.live_id:
                try:
                    await (await self._ch(self.live_id)).get_partial_message(int(t["live_card"])).delete()
                except discord.NotFound:
                    pass
            text, color = closed_text(t)
            await (await self._ch(self.closed_id)).send(embed=discord.Embed(description=text, color=color), silent=True)
            t["card_posted"], t["live_card"] = True, None
            await asyncio.to_thread(self.state.save)
        if not self.live_id or not led["open"]:
            return
        prices = await asyncio.to_thread(self.broker.position_details)
        ch = await self._ch(self.live_id)
        for sym, lot in led["open"].items():
            text, color = live_text(lot, (prices.get(sym) or {}).get("price"), L.stop_for(self.state, sym), today)
            embed = discord.Embed(description=text, color=color)
            if lot.get("card"):
                try:
                    await ch.get_partial_message(int(lot["card"])).edit(embed=embed)
                    continue
                except discord.NotFound:
                    lot["card"] = None
            lot["card"] = str((await ch.send(embed=embed, silent=True)).id)
            await asyncio.to_thread(self.state.save)
