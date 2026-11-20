"""claude-trader commands.

    python -m app                 show the active settings
    python -m app run             live: run the ORB bot every market day (alerts only in Step 1a)
    python -m app replay --date 2026-10-19 --offline day-trader-skill/tests/fixtures/trader-scanner/wall5m-2026-10-19.json.gz
                                  replay a past day from saved data, no network
    python -m app replay --date 2026-11-16 --symbols TSLA,NVDA,AMD
                                  replay a recent day (last ~5 sessions) from Yahoo
    python -m app check           Alpaca + Discord connection check
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import tempfile
from datetime import date, datetime, time as dtime
from pathlib import Path

from app import logs, market, paths, settings, strategies, tradelog
from app.routine import BotDay, DayData, LogAlerter
from app.scheduler import RealClock, SimClock, run_day, run_forever
from app.state import AppState


def show() -> int:
    rules = settings.risk_rules()
    print("claude-trader (Step 1a: alerts only, no orders)")
    print(f"  paper only: {rules['paper']}")
    print(f"  account ${rules['budget']:,}, max loss/trade ${rules['max_loss_per_trade_usd']}, "
          f"daily loss limit ${rules['max_daily_loss_usd']}")
    for s in strategies.load_enabled():
        w = s.settings["scan_window"]
        print(f"  [{s.id.upper()}] {s.name}: scan {w['start']}-{w['end']} ET, "
              f"stop {s.settings['exit']['stop']}, target {s.settings['exit']['target']}")
    return 0


async def results_and_summary(post, trade_log, day: str, session, rules: dict, orb, *,
                              run_id=None, only_if_new: bool = False, tries: int = 3,
                              scanned: bool = True) -> None:
    """After the close: work out every signal's result, then post the summary.
    Retries (10 minutes apart) if Alpaca's bars can't be fetched."""
    from app import afterclose, marketdata
    cost = orb.settings.get("costs", {}).get("pct_per_side", 0.0)
    for attempt in range(1, tries + 1):
        try:
            n = await asyncio.to_thread(afterclose.resolve_day, trade_log, day, fetch=marketdata.bars_5m,
                                        flat_by=afterclose.flat_by_for(session, rules), cost_pct=cost,
                                        run_id=run_id)
            break
        except Exception:  # noqa: BLE001
            if attempt == tries:
                logging.getLogger("app").exception("couldn't work out %s's results", day)
                return
            logging.getLogger("app").warning("results for %s failed (try %d), retrying in 10 min",
                                             day, attempt)
            await asyncio.sleep(600)
    if only_if_new and n == 0:
        return          # catch-up after a restart: nothing new, the summary was already posted
    extra = None
    focus_file = paths.RUNS_DIR / day / strategies.active_id() / "focus_symbols.json"
    if scanned and focus_file.exists() and session is not None:
        try:             # 1b.1 live audit: would full-market data have given the same signals?
            import json as _json
            check = await asyncio.to_thread(
                afterclose.data_check, trade_log, day, _json.loads(focus_file.read_text()),
                fetch=marketdata.bars_5m, session=session, settings=orb.settings, rules=rules,
                cost_pct=cost, run_id=run_id)
            (focus_file.parent / "data_check.json").write_text(_json.dumps(check, indent=1))
            extra = afterclose.data_check_line(check)
        except Exception:  # noqa: BLE001 - the audit never blocks the summary
            logging.getLogger("app").exception("data check for %s failed", day)
    from app import costs as _costs
    try:                 # 1b.8: today's real paper trades, costs vs the backtest, the running total
        paper = _costs.day_section(trade_log, day, cost)
    except Exception:  # noqa: BLE001
        logging.getLogger("app").exception("paper-trade summary for %s failed", day)
        paper = None
    extra = "\n\n".join(x for x in (paper, extra) if x) or None
    await post(afterclose.summary_text(trade_log, day, run_id=run_id, cost_pct=cost, scanned=scanned,
                                       extra=extra))


def daily_report(bot, day: str, trade_log=None):
    """2b.4: the after-close summary goes to the shared database; the head bot posts it in #daily-summary
    (one post a day for the whole fleet, each bot's detail in its thread). If the database can't take it,
    the bot posts it itself so it's never lost."""
    async def save(text: str) -> None:
        try:
            db = trade_log or tradelog.TradeLog()
            await asyncio.to_thread(db.save_report, strategies.active_id(), day, text)
        except Exception:  # noqa: BLE001
            logging.getLogger("app").warning("couldn't hand the summary to the head bot; posting it", exc_info=True)
            await bot.post_daily(text)
    return save


async def track_trades(bot, rules: dict) -> None:
    """Step 1b.5: Alpaca's live order events (fills, stops, targets) -> the books, #trades and the alert.
    Restarts the stream if it ever stops."""
    from alpaca.trading.stream import TradingStream
    from app.tracker import TradeTracker
    lg = logging.getLogger("app")
    al = settings.alpaca_settings()                     # paper only
    tracker = TradeTracker(tradelog.TradeLog(), rules)

    async def on_update(u) -> None:
        try:
            up = await asyncio.to_thread(tracker.handle, u.event, u.order)
            if up and bot.cards is not None:
                await bot.cards.sync_signal(up.signal_id)     # 1b.9: the trade's card says it all
            elif up:
                await bot.post_trades(up.text)
                await bot.note_on_alert(up.signal_id, up.line, up.state)
        except Exception:  # noqa: BLE001 - one bad event never stops tracking
            lg.exception("couldn't handle a trade update")

    while True:
        stream = TradingStream(al.api_key, al.secret_key, paper=True)
        stream.subscribe_trade_updates(on_update)
        try:
            await stream._run_forever()
            lg.warning("trade stream ended; restarting in 30 s")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            lg.exception("trade stream failed; restarting in 30 s")
        await asyncio.sleep(30)


async def restart_check(bot, calendar, rules: dict, orb) -> None:
    """Step 1b.7: on every start, line up the books with Alpaca (fills, exits, waiting entries,
    anything held while the market is closed)."""
    from app.reconcile import Reconciler
    lg = logging.getLogger("app")
    try:
        session = await asyncio.to_thread(calendar.session, datetime.now(market.NY).date())
        rec = Reconciler(bot.broker, tradelog.TradeLog(), rules,
                         int(orb.settings.get("orders", {}).get("fill_timeout_seconds", 120)))
        rep = await asyncio.to_thread(rec.reconcile, session)
    except Exception:  # noqa: BLE001
        lg.exception("restart check failed")
        return
    if rep.anything:
        await bot.post_system(rep.text())
        if bot.cards is None:
            for line in rep.trades:
                await bot.post_trades(f"🔄 {line}")
    for sid, line, st in rep.alert_updates:
        try:
            if bot.cards is not None:
                await bot.cards.sync_signal(sid)
            else:
                await bot.note_on_alert(sid, line, st)
        except Exception:  # noqa: BLE001
            lg.warning("couldn't update trade %s", sid, exc_info=True)
    if bot.cards is not None:
        try:
            await bot.cards.ensure_all()          # every open trade has a card (also after a restart)
        except Exception:  # noqa: BLE001
            lg.exception("couldn't set up live trade cards")
    for cid, wait in rep.recheck:                       # fill checks the restart interrupted
        async def later(cid=cid, wait=wait):
            await asyncio.sleep(max(wait, 0))
            out = await asyncio.to_thread(bot.desk.check_entry, cid)
            await bot.post_trades(out.text)
        asyncio.create_task(later())


async def heartbeat(every_s: int = 60, state: AppState | None = None, notify=None, bot=None) -> None:
    """Step 2b.3: tell the shared database this bot is alive (the head bot's watchdog reads it).
    2b.4: the note says whether it's paused, and the bot watches the head's heartbeat in turn
    (during market hours; a silent head never stops trading, it's just worth knowing)."""
    from datetime import timezone
    from app import head
    hb = tradelog.TradeLog()
    watch = head.head_watchdog()
    while True:
        try:
            own = state is not None and state.paused

            def write() -> None:
                note = "paused (own /pause)" if own else "paused (global)" if hb.global_pause() else "running"
                name = status = None
                if bot is not None:                 # for the head's /status <bot>
                    name = bot.user.name if bot.user else None
                    try:
                        status = bot.status_text()
                    except Exception:  # noqa: BLE001
                        status = None
                hb.beat(strategies.active_id(), note, name=name, status=status)
            await asyncio.to_thread(write)
            if notify is not None and state is not None:
                now = datetime.now(timezone.utc)
                beats = await asyncio.to_thread(hb.heartbeats)
                for text, ping in watch.check(beats, now, head.in_market_hours(now, state.session)):
                    await notify(text, ping=ping)
        except Exception:  # noqa: BLE001 - a missed beat is the watchdog's business, never the bot's
            logging.getLogger("app").warning("heartbeat failed", exc_info=True)
        await asyncio.sleep(every_s)


async def fleet_commands(bot, every_s: float = 5.0, trade_log=None) -> None:
    """Step 2b.4: carry out the head bot's commands (e.g. /flatten-all) with this bot's own keys,
    then answer in the shared database so the head can report."""
    db = trade_log or tradelog.TradeLog()
    me = strategies.active_id()
    while True:
        try:
            for c in await asyncio.to_thread(db.pending_commands, me):
                result = await run_fleet_command(bot, c["command"], c["note"])
                await asyncio.to_thread(db.ack_command, c["id"], me, result)
        except Exception:  # noqa: BLE001
            logging.getLogger("app").warning("fleet command check failed", exc_info=True)
        await asyncio.sleep(every_s)


async def run_fleet_command(bot, command: str, note: str | None = None) -> str:
    if command == "unping":                 # after the daily summary: no @mentions left on the day's cards
        cards = getattr(bot, "cards", None)
        if cards is None or not note:
            return "no closed-trade cards"
        n = await cards.unping(note)
        return f"took the @mention off {n} card{'' if n == 1 else 's'}"
    if command != "flatten":
        return f"unknown command {command!r}, ignored"
    if bot.flattener is None:
        return "nothing to close (ordering isn't set up)"
    rep, text = await bot.flatten_now("flatten all")
    await bot.post_system(text)
    await bot.after_flatten(rep, text)
    if not rep.anything:
        return "nothing was open"
    parts = [f"closed {len(rep.exits)}"] + ([f"cancelled {len(rep.cancelled_entries)} unfilled"]
                                           if rep.cancelled_entries else [])
    if rep.still_open:
        parts.append("⚠️ still open: " + ", ".join(rep.still_open))
    parts += [f"⚠️ {p}" for p in rep.problems]
    return " · ".join(parts)


async def live(dcfg, calendar, make_day, state, trade_log, rules, orb) -> None:
    """The Discord bot and the scheduler, side by side in one loop."""
    from app.discord_bot import DiscordAlerter, DiscordErrorHandler, TraderBot

    bot = TraderBot(dcfg, state)
    logging.getLogger().addHandler(DiscordErrorHandler(bot))
    from app.broker import AlpacaPaper
    from app.flatten import Flattener
    from app.orders import OrderDesk
    broker = AlpacaPaper()
    bot.broker = broker
    bot.desk = OrderDesk(tradelog.TradeLog(), broker, orb.settings, rules)   # Approve -> paper order
    pause_log = tradelog.TradeLog()                     # the head bot's global pause lives in the shared DB
    bot.desk.pause_source = lambda: state.paused or pause_log.global_pause()
    bot.flattener = Flattener(broker, tradelog.TradeLog(), rules)            # 3:55 PM and /flatten
    bot.assumed_cost = orb.settings.get("costs", {}).get("pct_per_side", 0.0)   # for /pnl
    if dcfg.channel_live_trades:                                             # 1b.9: trade cards
        from app.livecards import LiveCards
        from app.manage import TradeManager
        bot.cards = LiveCards(bot, tradelog.TradeLog(), TradeManager(broker, tradelog.TradeLog(), rules), rules,
                              live_channel=dcfg.channel_live_trades, closed_channel=dcfg.channel_closed_trades,
                              fill_timeout_s=int(orb.settings.get("orders", {}).get("fill_timeout_seconds", 120)),
                              session_fn=lambda: state.session)
    loop = asyncio.get_running_loop()
    me = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, me.cancel)
    async with bot:
        bot_task = asyncio.create_task(bot.start(dcfg.bot_token))
        ready = asyncio.create_task(bot.ready.wait())
        await asyncio.wait({bot_task, ready}, return_when=asyncio.FIRST_COMPLETED)
        if bot_task.done():
            bot_task.result()          # login failed: raise the reason
        alerter = DiscordAlerter(bot, loop)

        def make(day: str) -> BotDay:
            d = make_day(day, alerter)
            d.pause_source = lambda: state.paused or pause_log.global_pause()
            return d

        orders_on = bool(orb.settings.get("orders", {}).get("enabled"))
        await bot.post_system("🟢 **ORB bot online** · paper account · "
                              + ("**Approve places paper orders**" if orders_on else "alerts only, Approve just records")
                              + (" · ⏸️ still **paused** (`/resume` to turn alerts on)" if state.paused else ""))
        async def after_close(day_bot: BotDay) -> None:
            try:                    # exits booked before their fill price was known get the real price
                fixed = await asyncio.to_thread(bot.flattener.repair_exits, day_bot.day)
                for cid, sym, old_px, new_px, pnl in fixed:
                    old_txt = f"${old_px:,.2f}" if old_px is not None else "unknown"
                    await bot.post_system(f"🩹 Corrected {sym}'s exit: {old_txt} → ${new_px:,.2f} "
                                          f"(P&L {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f})")
                    if bot.cards is not None:
                        await bot.cards.refresh_closed(cid)
            except Exception:  # noqa: BLE001
                logging.getLogger("app").exception("couldn't repair today's exits")
            await results_and_summary(daily_report(bot, day_bot.day), trade_log, day_bot.day, state.session, rules, orb,
                                      run_id=day_bot.run_id,
                                      scanned=day_bot.scanned_today)
            if bot.cards is not None:
                try:
                    await bot.cards.add_backtest_lines(day_bot.day)
                except Exception:  # noqa: BLE001
                    logging.getLogger("app").warning("couldn't add backtest lines", exc_info=True)

        async def catch_up(day: str, session) -> None:
            await results_and_summary(daily_report(bot, day), trade_log, day, session, rules, orb, only_if_new=True)

        async def flatten(day_bot: BotDay, phase: str) -> None:
            rep = await asyncio.to_thread(bot.flattener.flatten, day_bot.day, phase)
            if rep.anything:
                await (bot.post_system if bot.cards is not None else bot.post_trades)(rep.text())
            for sid, line, st in rep.alert_updates:
                try:
                    if bot.cards is not None:
                        await bot.cards.sync_signal(sid)
                    else:
                        await bot.note_on_alert(sid, line, st)
                except Exception:  # noqa: BLE001
                    logging.getLogger("app").warning("couldn't update trade %s", sid, exc_info=True)

        sched = asyncio.create_task(run_forever(make, calendar, RealClock(), state=state,
                                                notify=bot.post_system, after_close=after_close,
                                                catch_up=catch_up, flatten=flatten))
        stream_task = asyncio.create_task(track_trades(bot, rules))
        asyncio.create_task(heartbeat(state=state, notify=bot.post_system, bot=bot))
        asyncio.create_task(fleet_commands(bot))
        if bot.cards is not None:
            asyncio.create_task(bot.cards.refresh_loop())
        asyncio.create_task(restart_check(bot, calendar, rules, orb))
        try:
            done, _ = await asyncio.wait({bot_task, sched}, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                t.result()
        except asyncio.CancelledError:
            logging.getLogger("app").info("Stopping")
            try:
                await asyncio.wait_for(bot.post_system("🔴 **ORB bot stopped.** No alerts until it's started again."), 10)
            except Exception:  # noqa: BLE001
                pass
        finally:
            sched.cancel()
            stream_task.cancel()


def single_instance():
    """Refuse to start a second copy (two copies would send every alert twice).
    The lock is released automatically when the process exits, even after a crash."""
    import fcntl
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = open(paths.DATA_DIR / "app.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.seek(0)
        print(f"Another copy of the app is already running (pid {f.read().strip() or '?'}). Not starting.")
        raise SystemExit(1)
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f   # keep it open for the life of the process


def cmd_run(a) -> int:
    if paths.IS_HEAD:                                    # 2b.4: BOT_ROLE=head runs the head bot instead
        from app import head
        return head.run()
    from alpaca.trading.client import TradingClient
    lock = single_instance()  # noqa: F841 - held until exit
    logs.setup()
    rules = settings.risk_rules()
    sid = os.environ.get("STRATEGY", "orb").strip().lower() or "orb"   # the bot this process runs
    strategies.set_active(sid)
    orb = strategies.load(sid)          # (named orb for history: it's whichever strategy STRATEGY says)
    al = settings.alpaca_settings()
    dcfg = settings.discord_settings()
    calendar = market.AlpacaCalendar(TradingClient(al.api_key, al.secret_key, paper=True))
    trade_log = tradelog.TradeLog()
    if trade_log.backend == "postgres":                  # 2b.3: first start on the shared DB moves the old log
        moved = tradelog.migrate_sqlite_to_postgres(tradelog.DEFAULT_DB, trade_log)
        if moved:
            logging.getLogger("app").info("moved the trade log into the shared database: %s", moved)
    state = AppState(started_at=datetime.now(market.NY))

    def make_day(day: str, alerter) -> BotDay:
        return BotDay(orb, rules, trade_log, source="live", day=day, alerter=alerter,
                      sec_user_agent=settings.sec_user_agent())

    try:
        asyncio.run(live(dcfg, calendar, make_day, state, trade_log, rules, orb))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    logging.getLogger("app").info("Stopped")
    return 0


def cmd_replay(a) -> int:
    strategies.set_active(a.strategy)
    logs.setup()
    rules = settings.risk_rules()
    orb = strategies.load(a.strategy)
    day = date.fromisoformat(a.date)
    session = market.SkillCalendar().session(day)
    if session is None:
        print(f"{day} is not a market day")
        return 1
    db = Path(a.db) if a.db else paths.DATA_DIR / "replays.db"   # replays never mix into the live log
    trade_log = tradelog.TradeLog(db)
    runs_root = paths.RUNS_DIR / "replay"
    day_data = None
    if a.offline:
        bundle = Path(a.offline)
        entry_dir = (Path(tempfile.mkdtemp(prefix="replay-")) if bundle.is_file() else bundle)
        if bundle.is_file():
            market.split_bundle(bundle, entry_dir)
        day_data = DayData(bars=bundle, entry_dir=entry_dir,
                           timemachine_dir=Path(a.timemachine_dir) if a.timemachine_dir else None,
                           news_dir=Path(a.news_dir) if a.news_dir else None)
    focus = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None
    if focus is None and day_data is None:
        print("A replay from Yahoo needs --symbols (the focus list can't be rebuilt for a past day).")
        return 1
    alerter = LogAlerter()
    day_bot = BotDay(orb, rules, trade_log, source="replay", day=day.isoformat(), alerter=alerter,
                     runs_root=runs_root, day_data=day_data, sec_user_agent=settings.sec_user_agent())
    clock = SimClock(datetime.combine(day, dtime(7, 0), tzinfo=market.NY))
    asyncio.run(run_day(day_bot, session, clock, simulated=True, focus=focus))

    if a.discord and alerter.sent:
        from app.discord_bot import alert_message, decision_view, post_once
        dcfg = settings.discord_settings()
        msgs = []
        for sid, res in alerter.sent:
            preview, embed = alert_message(sid, "replay", res)
            msgs.append((f"<@{dcfg.owner_id}> {preview}", embed, decision_view("replay", sid)))
        ids = asyncio.run(post_once(dcfg, dcfg.channel_setups, msgs))
        for (sid, _), mid in zip(alerter.sent, ids):
            trade_log.record_alert(sid, sent=True, channel_id=dcfg.channel_setups, message_id=mid)
        print(f"Posted {len(ids)} replay alerts to #setups. Buttons work while `python -m app run` is running.")

    rows = trade_log.signals(run_id=day_bot.run_id)
    print(f"\nReplay of {day} (run {day_bot.run_id}, saved in {db}):")
    print(f"  focus list {len(day_bot.focus)} stocks, {len(rows)} signals")
    for r in rows:
        al = trade_log.alert(r["id"])
        what = "ALERT" if al and al["sent"] else f"held ({al['held_reason']})" if al else "?"
        print(f"  {r['trigger_time']}  {r['symbol']:<6} {r['status']:<8} entry {r['entry'] or 0:>8.2f}"
              f"  stop {r['stop'] or 0:>8.2f}  target {r['target'] or 0:>8.2f}  qty {r['qty'] or '-':>4}  {what}")
    return 0


def cmd_summary(a) -> int:
    """Work out a day's results and print (or post) the summary."""
    from app import afterclose, marketdata
    logs.setup()
    rules = settings.risk_rules()
    orb = strategies.load("orb")
    db = Path(a.db) if a.db else (paths.DATA_DIR / ("tradelog.db" if a.source == "live" else "replays.db"))
    trade_log = tradelog.TradeLog(db)
    day = date.fromisoformat(a.date)
    cost = orb.settings.get("costs", {}).get("pct_per_side", 0.0)
    n = afterclose.resolve_day(trade_log, a.date, fetch=marketdata.bars_5m,
                               flat_by=afterclose.flat_by_for(market.SkillCalendar().session(day), rules),
                               cost_pct=cost, source=a.source, run_id=a.run)
    text = afterclose.summary_text(trade_log, a.date, source=a.source, run_id=a.run, cost_pct=cost)
    print(f"(worked out {n} new results)\n\n{text}")
    if a.post:
        from app.discord_bot import post_once
        dcfg = settings.discord_settings()
        asyncio.run(post_once(dcfg, dcfg.channel_daily_summary, [(text, None, None)]))
        print("\nPosted to #daily-summary.")
    return 0


def cmd_backtest_data(a) -> int:
    """Download (or reuse) the historical data a backtest needs."""
    from app.backtest import data
    logs.setup()
    orb = strategies.load("orb")
    out = data.prepare(date.fromisoformat(a.start), date.fromisoformat(a.end), orb.settings["focus_list"],
                       progress=lambda m: logging.getLogger("app").info("[backtest data] %s", m))
    print(out)
    return 0


def cmd_backtest_nq(a) -> int:
    """The NQ strategies (bar: Break and Retest; mrs: the scratched mean reversion): their own runners, same run
    numbering and reports; Uri posts them."""
    import importlib
    bt = importlib.import_module(f"app.backtest.{a.strategy}")
    logs.setup()
    res = bt.run(date.fromisoformat(a.start), date.fromisoformat(a.end), label=a.label, overrides=a.set or [],
                 progress=lambda m: logging.getLogger("app").info("[backtest] %s", m))
    m = res.headline
    print(f"\nRun #{res.run_id} ({res.label}): {m.get('sessions', m.get('days'))} sessions, {m['trades']} trades"
          + (f", {m['avg_r']:+.3f}R a trade after costs, total ${m['total_usd']:+,.0f}" if m["trades"] else ""))
    print(f"Report: {res.report_path}")
    if not a.no_post:
        print("Posted to #backtests (by Uri)." if bt.post(res.run_id) else
              "Not posted (set DISCORD_CHANNEL_BACKTESTS in .env to post runs to Discord).")
    return 0


def cmd_backtest(a) -> int:
    if a.strategy in ("mrs", "bar", "snap"):
        return cmd_backtest_nq(a)
    from app.backtest import run as bt
    logs.setup()
    res = bt.run(date.fromisoformat(a.start), date.fromisoformat(a.end), label=a.label, overrides=a.set or [],
                 progress=lambda m: logging.getLogger("app").info("[backtest] %s", m), strategy_id=a.strategy)
    m = res.headline
    print(f"\nRun #{res.run_id} ({res.label}): {m.get('trades', 0):,} trades, "
          f"{m.get('avg_r', 0):+.3f}R a trade after costs, total ${m.get('total_usd', 0):+,.0f}")
    if res.baseline:
        bm = res.baseline[2]
        print(f"  vs baseline run #{res.baseline[0]}: {m['avg_r'] - bm['avg_r']:+.3f}R a trade")
    print(f"Report: {res.report_path}")
    if not a.no_post:
        from app.backtest import post
        print("Posted to #backtests." if post.post(res.run_id) else
              "Not posted (set DISCORD_CHANNEL_BACKTESTS in .env to post runs to Discord).")
    return 0


def cmd_backtest_post(a) -> int:
    from app.backtest import post
    if not post.post(a.run):
        print("DISCORD_CHANNEL_BACKTESTS isn't set in .env.")
        return 1
    print(f"Posted run #{a.run} to #backtests.")
    return 0


def main(argv=None) -> int:
    settings.load_env()
    p = argparse.ArgumentParser(prog="python -m app")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="live: run the ORB bot every market day")
    r = sub.add_parser("replay", help="replay a past day on a simulated clock")
    r.add_argument("--date", required=True, help="YYYY-MM-DD")
    r.add_argument("--offline", help="saved 5m bars: a {TICKER: chart} bundle or a folder of <TICKER>.json")
    r.add_argument("--timemachine-dir", help="folder of <TICKER>.json(.gz) with ~60 days of 5m bars")
    r.add_argument("--news-dir", help="folder of saved headlines / filings (trader-news format)")
    r.add_argument("--symbols", help="comma-separated focus list (default: every ticker in --offline)")
    r.add_argument("--db", help="trade log file (default data/replays.db)")
    r.add_argument("--discord", action="store_true", help="also post the alerts to #setups (marked REPLAY)")
    r.add_argument("--strategy", default="orb", help="which strategy bot to replay (default: orb)")
    sm = sub.add_parser("summary", help="work out a day's results and print the summary")
    sm.add_argument("--date", required=True, help="YYYY-MM-DD")
    sm.add_argument("--source", default="live", choices=["live", "replay"])
    sm.add_argument("--run", type=int, help="only this run (e.g. one replay)")
    sm.add_argument("--db", help="trade log file (default: the live or replay log)")
    sm.add_argument("--post", action="store_true", help="also post it to #daily-summary")
    bd = sub.add_parser("backtest-data", help="download (or reuse) historical bars for a backtest")
    bd.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    bd.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    bt = sub.add_parser("backtest", help="run a backtest of the ORB bot and write its report")
    bt.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    bt.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    bt.add_argument("--label", required=True, help='a name for the run, e.g. "baseline" or "1R target"')
    bt.add_argument("--strategy", default="orb", help="which strategy bot to backtest (default: orb)")
    bt.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="change a setting for this run only, e.g. exit.target=1R, risk.max_trades_per_day=2, "
                         "selection.cash_limit=false (repeatable)")
    bt.add_argument("--no-post", action="store_true", help="don't post the summary to #backtests")
    bp = sub.add_parser("backtest-post", help="(re)post a backtest run's summary to #backtests")
    bp.add_argument("--run", type=int, required=True)
    sub.add_parser("check", help="Alpaca + Discord connection check")
    a = p.parse_args(argv)
    if a.cmd == "backtest-post":
        return cmd_backtest_post(a)
    if a.cmd == "backtest":
        return cmd_backtest(a)
    if a.cmd == "backtest-data":
        return cmd_backtest_data(a)
    if a.cmd == "summary":
        return cmd_summary(a)
    if a.cmd == "run":
        return cmd_run(a)
    if a.cmd == "replay":
        return cmd_replay(a)
    if a.cmd == "check":
        from app import check
        return check.main()
    return show()


if __name__ == "__main__":
    raise SystemExit(main())
