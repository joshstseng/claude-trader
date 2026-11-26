"""Swing v1.1's live process (STRATEGY=swing): its own Discord client, a tick every 5 seconds, a heartbeat for Uri's
watchdog, Uri's fleet commands, and information-only trade cards that @mention the owner until Uri's daily summary.
Rules live in app/strategies/swing.py."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from datetime import date, datetime, time as dtime, timedelta, timezone

from app import market, settings, strategies, swing_live as L, tradelog

log = logging.getLogger(__name__)
NY = L.NY


def bar_rows(data_client, sym: str, start: datetime, end: datetime | None, feed):
    from alpaca.data.enums import Adjustment
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    got = data_client.get_stock_bars(StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame(5, TimeFrameUnit.Minute), feed=feed,
                                                      adjustment=Adjustment.ALL, start=start, end=end)).data
    return [(b.timestamp, b.open, b.high, b.low, b.close) for b in got.get(sym, [])]


async def unping_cards(ch, trades: list[dict], day: str) -> int:
    """Take the @mention off one day's closed cards after Uri's summary. Editing never pings again."""
    import discord
    from app.discord_bot import MENTION_RE
    n = 0
    for t in trades:
        if t["day"] != day or not t.get("closed_card"):
            continue
        try:
            msg = await ch.fetch_message(int(t["closed_card"]))
        except discord.NotFound:
            continue
        if MENTION_RE.match(msg.content or ""):
            await msg.edit(content=MENTION_RE.sub("", msg.content, count=1))
            n += 1
    return n


async def live() -> None:
    import discord
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    al, cfg = settings.alpaca_settings(), settings.discord_settings()
    s = L.load_settings()
    sym, run_mode = s["symbol"], L.mode()
    broker = L.AlpacaSwing(sym)
    data = StockHistoricalDataClient(al.api_key, al.secret_key)
    calendar = market.AlpacaCalendar(TradingClient(al.api_key, al.secret_key, paper=True))
    db, hb, cmds = tradelog.TradeLog(), tradelog.TradeLog(), tradelog.TradeLog()
    state = L.State()
    client = discord.Client(intents=discord.Intents(guilds=True))
    ready = asyncio.Event()
    busy = asyncio.Lock()
    channels = {"setups": cfg.channel_setups, "system": cfg.channel_system}
    loop = asyncio.get_running_loop()

    @client.event
    async def on_ready():
        ready.set()

    async def post_async(where: str, text: str, ping: bool) -> None:
        await ready.wait()
        ch = client.get_channel(channels[where]) or await client.fetch_channel(channels[where])
        await ch.send((f"<@{cfg.owner_id}> " if ping else "") + text[:1900])

    def post(where: str, text: str, ping: bool) -> None:      # the routine runs in a worker thread
        asyncio.run_coroutine_threadsafe(post_async(where, text, ping), loop).result(timeout=20)

    def history(day: date):
        start = datetime.combine(day - timedelta(days=280), dtime(0), tzinfo=NY)
        end = datetime.combine(day, dtime(0), tzinfo=NY)            # prior sessions only, so SIP's delay doesn't matter
        return L.matrix(bar_rows(data, sym, start, end, DataFeed.SIP))

    def today(day: date):
        return bar_rows(data, sym, datetime.combine(day, dtime(9, 30), tzinfo=NY), None, DataFeed.IEX)   # real-time feed

    routine = L.Routine(s, state, calendar, broker, history, today, post, lambda d, t: db.save_report("swing", d, t),
                        db.global_pause, run_mode, publish=lambda d, x: db.set_fleet(f"daily:swing:{d}", json.dumps(x)))

    async def channel(cid):
        return client.get_channel(cid) or await client.fetch_channel(cid)

    async def cards():
        """Every 20 seconds: one live card while in a trade, and one closed card per exit."""
        await ready.wait()
        while run_mode == "paper":
            try:
                async with busy:
                    led = state.ledger
                    for t in led["closed"]:
                        if t["card_posted"]:
                            continue
                        if t.get("live_card") and cfg.channel_live_trades:
                            try:
                                await (await channel(cfg.channel_live_trades)).get_partial_message(int(t["live_card"])).delete()
                            except discord.NotFound:
                                pass
                        head, body, color = L.closed_message(t, sym, cfg.owner_id)
                        out = await (await channel(cfg.channel_closed_trades)).send(head, embed=discord.Embed(description=body, color=color))
                        t["card_posted"], t["live_card"], t["closed_card"] = True, None, str(out.id)
                        await asyncio.to_thread(state.save)
                    lot = led["open"]
                    if lot and cfg.channel_live_trades:
                        _, px = await asyncio.to_thread(broker.position)
                        title, text, color = L.live_text(lot, sym, px, state.day(lot["day"]))
                        embed = discord.Embed(title=title, description=text, color=color)
                        ch = await channel(cfg.channel_live_trades)
                        try:
                            if lot.get("card"):
                                await ch.get_partial_message(int(lot["card"])).edit(embed=embed)
                            else:
                                lot["card"] = str((await ch.send(L.live_ping(lot, sym, cfg.owner_id), embed=embed)).id)
                                await asyncio.to_thread(state.save)
                        except discord.NotFound:
                            lot["card"] = None
                    await asyncio.to_thread(db.set_fleet, "numbers:swing", json.dumps(L.numbers(state)))
            except Exception:  # noqa: BLE001 - cards never get in the way of trading
                log.warning("couldn't update Swing's cards", exc_info=True)
            await asyncio.sleep(20)

    async def ticks():
        while True:
            try:
                async with busy:
                    await asyncio.to_thread(routine.tick, datetime.now(timezone.utc))
            except Exception:  # noqa: BLE001 - a bad tick must not end the bot
                log.exception("tick failed")
            await asyncio.sleep(5)

    async def beats():
        while True:
            try:
                note = "paused (global)" if await asyncio.to_thread(hb.global_pause) else f"running ({run_mode})"
                name = client.user.name if client.user else None
                status = routine.status_text(datetime.now(NY).date().isoformat())
                await asyncio.to_thread(hb.beat, "swing", note, name=name, status=status)
            except Exception:  # noqa: BLE001
                log.warning("heartbeat failed", exc_info=True)
            await asyncio.sleep(60)

    async def commands():
        while True:
            try:
                for c in await asyncio.to_thread(cmds.pending_commands, "swing"):
                    if c["command"] == "flatten":
                        async with busy:
                            result = await asyncio.to_thread(routine.flatten, datetime.now(NY).date().isoformat())
                        await post_async("system", f"🛑 **Swing v1.1 flatten:** {result}", False)
                    elif c["command"] == "unping":
                        async with busy:
                            trades = list(state.ledger["closed"])
                        n = await unping_cards(await channel(cfg.channel_closed_trades), trades, c["note"])
                        result = f"took the @mention off {n} card{'' if n == 1 else 's'}"
                    elif c["command"] == "swing-test-cards":
                        lot = {"side": 1, "qty": 120, "entry": 638.10, "time": "10:05:12", "why": "breakout above the band (TEST)"}
                        rec = {"done_bar": 13, "v11": {"side": 1, "up": [637.0] * 78, "down": [630.0] * 78, "lo": 635.5, "hi": None}}
                        title, text, color = L.live_text(lot, sym, 639.10, rec)
                        await (await channel(cfg.channel_live_trades)).send(
                            L.live_ping(lot, sym, cfg.owner_id) + " · TEST", embed=discord.Embed(title=title, description=text + "\n-# TEST card, safe to delete", color=color))
                        head, body, color = L.closed_message({"side": 1, "qty": 120, "entry": 638.10, "exit": 638.19, "pnl": 11.07, "time_in": "10:05:12",
                                                              "time_out": "10:40:03", "why": "back inside the band (TEST)"}, sym, cfg.owner_id)
                        await (await channel(cfg.channel_closed_trades)).send(head + " · TEST", embed=discord.Embed(description=body + "\n-# TEST card, safe to delete", color=color))
                        result = "posted test cards"
                    elif c["command"] == "swing-morning-preview":
                        async with busy:
                            result = await asyncio.to_thread(routine.morning_preview, c["note"])
                    else:
                        result = f"unknown command {c['command']!r}, ignored"
                    await asyncio.to_thread(cmds.ack_command, c["id"], "swing", result)
            except Exception:  # noqa: BLE001
                log.warning("fleet command check failed", exc_info=True)
            await asyncio.sleep(5)

    me = asyncio.current_task()
    for sg in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sg, me.cancel)
    async with client:
        bot = asyncio.create_task(client.start(cfg.bot_token))
        wait = asyncio.create_task(ready.wait())
        await asyncio.wait({bot, wait}, return_when=asyncio.FIRST_COMPLETED)
        if bot.done():
            bot.result()
        equity = await asyncio.to_thread(broker.equity)
        await post_async("system", f"🟢 **Swing v1.1 online** · {'**paper orders on**' if run_mode == 'paper' else '👻 shadow, no orders'}"
                         f" · account ${equity:,.0f}", False)
        try:
            have = {k.rsplit(":", 1)[1] for k, _ in await asyncio.to_thread(db.fleet_prefix, "daily:swing:")}
            async with busy:
                n = await asyncio.to_thread(routine.backfill, have)
            if n:
                log.info("published %d missing daily records", n)
        except Exception:  # noqa: BLE001 - the journal must never stop the bot
            log.warning("daily record backfill failed", exc_info=True)
        tasks = [asyncio.create_task(x()) for x in (ticks, beats, commands, cards)]
        try:
            await bot
        except asyncio.CancelledError:
            log.info("Stopping")
            try:
                await asyncio.wait_for(post_async("system", "🔴 **Swing v1.1 stopped.** No new orders until it's back.", False), 10)
            except Exception:  # noqa: BLE001
                pass
        finally:
            for x in tasks:
                x.cancel()


def run() -> int:
    strategies._active["id"] = "swing"          # logs and heartbeats say Swing; it isn't a day-trading brain
    log.info("Swing v1.1 starting: %s", "paper orders ON" if L.mode() == "paper" else "shadow mode, no orders")
    try:
        asyncio.run(live())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    log.info("Stopped")
    return 0
