"""Bumi's live process (STRATEGY=bumi): one Discord client, a tick every 20 seconds, a heartbeat for Uri's watchdog,
and Uri's fleet commands. Trading logic lives in app/bumi_live.py and app/strategies/bumi.py."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from datetime import date, datetime, time as dtime, timedelta, timezone

from app import bumi_live as L
from app.bumi_cards import BumiCards
from app import market, settings, strategies, tradelog, vix as vixdata
from app.research.data import D
from app.strategies import bumi

log = logging.getLogger(__name__)
NY = L.NY
RETRY_S = 300
VIX_WAIT_UNTIL = dtime(19, 0)   # after this, decide without a fresh VIX: exits run, new buys don't
HISTORY_FROM = date(2016, 1, 1)


def prev_session(calendar, day: date) -> date | None:
    for back in range(1, 11):
        d = day - timedelta(days=back)
        if calendar.session(d):
            return d
    return None


def latest_done(calendar, now: datetime) -> date | None:
    """The newest session whose after-close decision is due."""
    t = now.astimezone(NY)
    s = calendar.session(t.date())
    if s and t >= s.at(s.close) + timedelta(minutes=L.AFTER_CLOSE_MIN):
        return t.date()
    return prev_session(calendar, t.date())


def fetch_inputs(data_client, s: dict, day: date, now: datetime):
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    syms = list(s["universe"]) + list(s["universe"].values())
    end = min(datetime.combine(day, dtime(23, 59), tzinfo=NY), now.astimezone(timezone.utc) - timedelta(minutes=20))
    got = data_client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=syms, timeframe=TimeFrame.Day, feed=DataFeed.SIP, adjustment=Adjustment.ALL,
        start=datetime.combine(HISTORY_FROM, dtime(0), tzinfo=NY), end=end)).data
    bars = {u: [D(datetime.combine(b.timestamp.astimezone(NY).date(), dtime(0), tzinfo=NY), b.open, b.high, b.low,
                  b.close, b.volume) for b in got.get(u, [])] for u in syms}
    closes = {u: v[-1].c for u, v in bars.items() if v and v[-1].t.date() == day}
    v = vixdata.fetch(day)
    aligned, series, fresh = L.align({u: bars[u] for u in s["universe"]}, v.series, day, v.fresh)
    return aligned, series, fresh, closes, v.note


BREAKER_CONTEXT = {
    "bad_day": "Bumi's worst day in 25 years of backtesting (2001 to 2026) was -7.5%, so a day like this is unusual: "
               "a market shock, or something off with Bumi itself.",
    "drawdown": "Bumi's backtest fell this far about once every 5 years (2002, 2008, 2010, Feb 2020, Jan 2022) and "
                "recovered each time. Its worst drop was -25%. Painful, but it has happened before.",
}


def breaker_text(kind: str, what: str) -> str:
    """The breaker ping: what happened, what Bumi does now, why the check exists, and what to look at."""
    if kind == "bad_day":
        head = (f"🛑 **Bumi paused new buys:** {what}.\n\n"
                "**What this does:** no new trades until you lift the pause. Bumi keeps its positions, and its normal exits "
                "(trailing stops, leaving the core when the market isn't calm) still run. **Nothing was sold because of this.**\n\n")
        then = ("• **Then:** `/resume-bumi` if it's normal market pain. If something looks broken, leave it paused or "
                "`/flatten-bumi confirm:yes`, and tell Claude what you saw.")
    else:
        head = (f"⚠️ **Bumi alert:** {what}.\n\n"
                "**What this does:** nothing changes. **Bumi keeps trading as normal**, including buying dips, which is "
                "often where its recoveries come from. Nothing was paused or sold. This is just so you know.\n\n")
        then = ("• **Then:** usually nothing to do. If something looks broken, `/pause-bumi` stops new orders, or "
                "`/flatten-bumi confirm:yes` sells everything; tell Claude what you saw.")
    return (head + f"**Why you're getting this:** a check so you look before Bumi keeps adding money in unusual conditions. "
            f"{BREAKER_CONTEXT[kind]}\n\n**No need to panic. Worth checking:**\n"
            "• **The market:** is this a broad selloff? Look at QQQ, SPY and VIX.\n"
            "• **Bumi:** do its recent fills and positions in `#system` and its Alpaca account look right?\n" + then)


def bot_command(command: str, state, run_mode: str, broker) -> tuple[str | None, str]:
    """Uri's Bumi-only controls (/pause-bumi, /resume-bumi, /flatten-bumi). Returns (what to post or None, the ack)."""
    if command == "pause:bumi":
        state.doc["paused"] = True
        state.save()
        return "⏸️ **Bumi paused** by `/pause-bumi`: no new orders. Positions are kept and Swing is unaffected.", "paused"
    if command == "resume:bumi":
        was = state.doc.get("buys_paused")
        state.doc["paused"], state.doc["buys_paused"] = False, None
        state.save()
        return "▶️ **Bumi resumed** by `/resume-bumi`" + (f" (new buys were paused: {was})" if was else "") + ".", "resumed"
    if command == "flatten:bumi":
        state.doc["paused"] = True
        result = L.flatten(state, run_mode, broker)
        return f"🛑 **Bumi flattened** by `/flatten-bumi`: {result}. Bumi is paused until `/resume-bumi`.", f"flattened: {result}"
    return None, f"unknown command {command!r}, ignored"


def plan_text(rec: dict, held: dict[str, int] | None) -> str:
    p = rec["plan"]
    head = (f"📋 **Bumi's plan for the next open** · from {date.fromisoformat(p['as_of']):%a %b %-d}'s close"
            + (" · 👻 shadow" if rec["mode"] not in L.ORDERS else " · 🔴 live" if rec["mode"] == "live" else ""))
    vix = f"VIX **{p['vix']:.2f}**" + ("" if p["vix_fresh"] else " ⚠️ stale, no new buys")
    lines = [head, f"{vix} · Market: **{'calm' if p['calm'] else 'not calm'}**"]
    if rec["orders"]:
        lines += [f"• **{o['side'].upper()} {o['qty']} {o['sym']}** at the open · {o['why']}" for o in rec["orders"]]
    else:
        lines.append("No trades.")
    stops = [f"{r['etf']} (stop on {r['sym']} {r['stop']:.2f})" for r in p["rows"] if r["action"] == "hold"]
    if stops:
        lines.append("Open dip trades: " + ", ".join(stops))
    if held is not None:
        lines.append("Holding: " + (", ".join(f"{q} {u}" for u, q in sorted(held.items())) or "cash"))
    lines += [f"⚠️ {n}" for n in rec["notes"]]
    return "\n".join(lines)


class Routine:
    """One tick of Bumi's day. Everything external is passed in, so tests run it on a fake clock and broker."""

    def __init__(self, s, state, calendar, broker, fetch, post, report, paused, run_mode, publish=None, opens=None):
        self.s, self.state, self.cal, self.broker = s, state, calendar, broker
        self.publish, self.opens = publish, opens          # Uri's weekly check: publish(day, dict); opens(day, syms) -> {sym: open}
        self.fetch, self.post, self.report, self.paused, self.mode = fetch, post, report, paused, run_mode
        self.retry_at: datetime | None = None
        self.warned: set[str] = set()
        self.reported: set[str] = set()
        self.send_noted: set[str] = set()

    def holdings(self):
        return self.broker.positions() if self.mode in L.ORDERS else dict(self.state.doc["virtual"])

    async def tick(self, now: datetime) -> None:
        t = now.astimezone(NY)
        session = await asyncio.to_thread(self.cal.session, t.date())
        if session and t >= session.at(session.close) + timedelta(minutes=15):
            await self.hand_in_report(t.date())
        done = await asyncio.to_thread(latest_done, self.cal, now)
        if done and not self.state.day(done.isoformat()):
            await self.try_decide(done, now)
        if not session:
            return
        prev = await asyncio.to_thread(prev_session, self.cal, t.date())
        key = prev.isoformat() if prev else ""
        rec = self.state.day(key)
        if rec and rec["mode"] in L.ORDERS and not rec["sent"] and session.at(L.SEND_AT) <= t <= session.at(L.LAST_SEND):
            await self.send(key, now, rec)
        if rec and rec["mode"] in L.ORDERS and rec["sent"] and not rec["confirmed"] and rec["orders"] \
                and t >= session.at(L.CONFIRM_AFTER):
            await self.confirm(key, rec, t.date().isoformat())

    async def hand_in_report(self, day: date) -> None:
        """Uri's daily summary waits for every bot, so this goes in on time, before the 4:30 PM decision."""
        key = day.isoformat()
        if key in self.reported:
            return
        try:
            held = await asyncio.to_thread(self.holdings)
            text = ("Holding: " + (", ".join(f"{q} {u}" for u, q in sorted(held.items())) or "cash")
                    + f" · {self.mode} mode\nTomorrow's plan posts in #setups about 30 minutes after the close.")
            await asyncio.to_thread(self.report, key, text)
            self.reported.add(key)
            if self.mode in L.ORDERS:
                eq = await asyncio.to_thread(self.broker.equity)
                alert = await asyncio.to_thread(L.track_equity, self.state, key, eq, L.size_fraction(), self.s)
                if alert:
                    await self.post("system", breaker_text(*alert), True)
        except Exception:  # noqa: BLE001
            log.warning("couldn't hand in the daily report", exc_info=True)

    async def try_decide(self, day: date, now: datetime) -> None:
        if self.retry_at and now < self.retry_at:
            return
        key = day.isoformat()
        waited = now.astimezone(NY) >= datetime.combine(day, VIX_WAIT_UNTIL, tzinfo=NY)
        try:
            bars, series, fresh, closes, note = await asyncio.to_thread(self.fetch, day, now)
            if not fresh and not waited:
                log.info("waiting for %s's VIX close: %s", key, note)
                self.retry_at = now + timedelta(seconds=RETRY_S)
                return
            plan = bumi.plan_next(bars, series, self.s, vix_fresh=fresh)
            if plan["as_of"] != key:
                raise ValueError(f"plan is for {plan['as_of']}, expected {key}")
            rec = await asyncio.to_thread(L.decide, plan, self.s, self.state, closes, self.mode, self.broker)
            self.retry_at = None
            await self.post("setups", plan_text(rec, await asyncio.to_thread(self.holdings)), False)
            if self.publish is not None:
                try:
                    await asyncio.to_thread(self.publish, key, await asyncio.to_thread(self.daily_record, day, rec))
                except Exception:  # noqa: BLE001 - the weekly check must never get in the way of trading
                    log.warning("couldn't publish the daily record", exc_info=True)
        except Exception as e:  # noqa: BLE001 - no plan means no orders; keep retrying and say so once
            log.exception("couldn't decide for %s", key)
            self.retry_at = now + timedelta(seconds=RETRY_S)
            if waited and key not in self.warned:
                self.warned.add(key)
                await self.post("system", f"⚠️ **Bumi has no plan for {key}** ({type(e).__name__}). No orders will be "
                                "sent until it can read final prices. Still retrying.", True)

    def daily_record(self, day: date, rec: dict) -> dict:
        """Today's plan, plus this morning's opening fills checked against the official open (final after the close)."""
        prev = prev_session(self.cal, day)
        before = self.state.day(prev.isoformat()) if prev else None
        orders = [o for o in (before or {}).get("orders", []) if o.get("filled_price")]
        opens = {}
        if orders and self.opens is not None:
            try:
                opens = self.opens(day, sorted({o["sym"] for o in orders}))
            except Exception:  # noqa: BLE001
                log.warning("no opening prices for the fill check", exc_info=True)
        fills = []
        for o in orders:
            op = opens.get(o["sym"])
            slip = ((o["filled_price"] - op) / op * 1e4 * (1 if o["side"] == "buy" else -1)) if op else None
            fills.append({"sym": o["sym"], "side": o["side"], "qty": o["filled_qty"], "price": o["filled_price"], "open": op,
                          "slip_bp": round(slip, 2) if slip is not None else None})
        planned = (before or {}).get("orders", [])
        return {"day": day.isoformat(), "mode": self.mode, "plan_orders": len(rec["orders"]), "vix": rec["plan"]["vix"],
                "calm": rec["plan"]["calm"], "fills": fills,
                "filled_all": all(o.get("filled_qty") == o["qty"] for o in planned) if planned and (before or {}).get("sent") else None}

    async def send(self, key: str, now: datetime, rec: dict) -> None:
        paused = await asyncio.to_thread(self.paused)
        if paused:
            if key not in self.send_noted:
                self.send_noted.add(key)
                await self.post("system", "⏸️ Bumi is paused, so this morning's orders were not sent.", False)
            return
        problems = await asyncio.to_thread(L.send, key, now, self.state, self.mode, self.broker, False)
        if rec["orders"]:
            lines = [f"`{o['side']} {o['qty']} {o['sym']}`: {o['status']}" for o in rec["orders"]]
            bad = any(str(o["status"]).startswith("failed") for o in rec["orders"])
            await self.post("system", ("⚠️ **Bumi: an order failed**\n" if bad else "📨 **Bumi sent its opening orders**\n")
                            + "\n".join(lines), bad)
        elif problems and problems != ["already sent"]:
            log.info("send: %s", problems)

    def awaiting_fills(self) -> bool:
        return any(r["mode"] in L.ORDERS and r["sent"] and r["orders"] and not r["confirmed"]
                   for r in self.state.doc["days"].values())

    async def confirm(self, key: str, rec: dict, fill_day: str | None = None) -> None:
        try:
            problems = await asyncio.to_thread(L.confirm, key, self.state, self.broker, fill_day, self.s)
        except Exception:  # noqa: BLE001
            log.warning("fill check failed, will retry", exc_info=True)
            return
        if problems:
            await self.post("system", "⚠️ **Bumi's fills need a look**\n" + "\n".join(problems), True)
        else:
            lines = [f"`{o['side']} {o['filled_qty']} {o['sym']}` at ${o['filled_price']:,.2f}" for o in rec["orders"]]
            await self.post("system", "✅ **Bumi's orders filled**\n" + "\n".join(lines), False)

    def status_text(self) -> str:
        days = sorted(self.state.doc["days"])
        if not days:
            return f"{self.mode} mode · no plan yet"
        p = self.state.doc["days"][days[-1]]["plan"]
        return (f"{self.mode} mode · last plan {p['as_of']} · VIX {p['vix']:.2f} · "
                f"{'calm' if p['calm'] else 'not calm'} · {len(self.state.doc['days'][days[-1]]['orders'])} orders")


async def live() -> None:
    import discord
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    run_mode = L.mode()                         # raises on a partial live setup, before any broker call
    al, cfg = settings.alpaca_settings(allow_live=run_mode == "live"), settings.discord_settings()
    s = L.load_settings()
    fraction = L.size_fraction()
    broker = L.AlpacaBumi(live=run_mode == "live")
    data_client = StockHistoricalDataClient(al.api_key, al.secret_key)
    calendar = market.AlpacaCalendar(TradingClient(al.api_key, al.secret_key, paper=al.paper))
    db, hb, cmds = tradelog.TradeLog(), tradelog.TradeLog(), tradelog.TradeLog()
    state = L.State()
    client = discord.Client(intents=discord.Intents(guilds=True))
    ready = asyncio.Event()
    busy = asyncio.Lock()
    channels = {"setups": cfg.channel_setups, "system": cfg.channel_system}

    @client.event
    async def on_ready():
        ready.set()

    async def post(where: str, text: str, ping: bool) -> None:
        await ready.wait()
        ch = client.get_channel(channels[where]) or await client.fetch_channel(channels[where])
        await ch.send((f"<@{cfg.owner_id}> " if ping else "") + text[:1900])

    def opens(day: date, syms: list[str]) -> dict[str, float]:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        got = data_client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=syms, timeframe=TimeFrame.Day, feed=DataFeed.SIP, adjustment=Adjustment.RAW,
            start=datetime.combine(day, dtime(0), tzinfo=NY), end=datetime.now(timezone.utc) - timedelta(minutes=20))).data
        return {u: float(b[0].open) for u, b in got.items() if b and b[0].timestamp.astimezone(NY).date() == day}

    routine = Routine(s, state, calendar, broker, lambda d, n: fetch_inputs(data_client, s, d, n), post,
                      lambda d, t: db.save_report("bumi", d, t), lambda: db.global_pause() or bool(state.doc.get("paused")), run_mode,
                      publish=lambda d, x: db.set_fleet(f"daily:bumi:{d}", json.dumps(x)), opens=opens)

    live_cards = BumiCards(state, broker, lambda c: client.get_channel(c) or client.fetch_channel(c),
                           cfg.channel_live_trades, cfg.channel_closed_trades)

    async def ledger():
        """Every minute: positions closed outside the plan, the trade cards, and Uri's numbers."""
        await ready.wait()
        while run_mode in L.ORDERS:
            try:
                async with busy:
                    today = datetime.now(NY).date().isoformat()
                    if not routine.awaiting_fills():
                        notes = await asyncio.to_thread(L.reconcile, state, broker, s, today)
                        if notes:
                            await post("system", "⚠️ **Bumi's positions need a look**\n" + "\n".join(notes), True)
                    await live_cards.sync(today)
                    await asyncio.to_thread(db.set_fleet, "numbers:bumi", json.dumps(L.numbers(state)))
            except Exception:  # noqa: BLE001 - cards never get in the way of trading
                log.warning("couldn't update Bumi's cards", exc_info=True)
            await asyncio.sleep(60)

    async def ticks():
        while True:
            try:
                async with busy:
                    await routine.tick(datetime.now(timezone.utc))
            except Exception:  # noqa: BLE001 - a bad tick must not end the bot
                log.exception("tick failed")
            await asyncio.sleep(20)

    async def beats():
        while True:
            try:
                note = ("paused (global)" if await asyncio.to_thread(hb.global_pause) else "paused (Bumi)" if state.doc.get("paused")
                        else f"running ({run_mode}, new buys paused)" if state.doc.get("buys_paused") else f"running ({run_mode})")
                name = client.user.name if client.user else None
                await asyncio.to_thread(hb.beat, "bumi", note, name=name, status=routine.status_text())
            except Exception:  # noqa: BLE001
                log.warning("heartbeat failed", exc_info=True)
            await asyncio.sleep(60)

    async def commands():
        while True:
            try:
                for c in await asyncio.to_thread(cmds.pending_commands, "bumi"):
                    if c["command"] == "flatten":
                        async with busy:
                            result = await asyncio.to_thread(L.flatten, state, run_mode, broker)
                        await post("system", f"🛑 **Bumi flatten:** {result}", False)
                    elif c["command"] == "unping":
                        result = "no closed-trade cards"
                    else:
                        async with busy:
                            text, result = await asyncio.to_thread(bot_command, c["command"], state, run_mode, broker)
                        if text:
                            await post("system", text, False)
                    await asyncio.to_thread(cmds.ack_command, c["id"], "bumi", result)
            except Exception:  # noqa: BLE001
                log.warning("fleet command check failed", exc_info=True)
            await asyncio.sleep(5)

    loop = asyncio.get_running_loop()
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
        if run_mode == "live":
            await post("system", f"🔴 **Bumi LIVE · REAL MONEY** · account ${equity:,.0f} · trading as {fraction:.0%} of it "
                       f"(${equity * fraction:,.0f})", True)
        else:
            await post("system", f"🟢 **Bumi online** · {'**paper orders on**' if run_mode == 'paper' else '👻 shadow, no orders'}"
                       f" · account ${equity:,.0f}" + (f" · trading as {fraction:.0%} of it" if fraction < 1 else ""), False)
        tasks = [asyncio.create_task(x()) for x in (ticks, beats, commands, ledger)]
        try:
            await bot
        except asyncio.CancelledError:
            log.info("Stopping")
            try:
                await asyncio.wait_for(post("system", "🔴 **Bumi stopped.** No plans or orders until it's back.", False), 10)
            except Exception:  # noqa: BLE001
                pass
        finally:
            for x in tasks:
                x.cancel()


def run() -> int:
    strategies._active["id"] = "bumi"           # logs and heartbeats say Bumi; it isn't a day-trading brain
    if L.mode() in L.ORDERS:
        log.info("Bumi starting: paper orders ON")
    else:
        log.info("Bumi starting: shadow mode, no orders")
    try:
        asyncio.run(live())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    log.info("Stopped")
    return 0
