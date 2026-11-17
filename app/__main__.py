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
import tempfile
from datetime import date, datetime, time as dtime
from pathlib import Path

from app import logs, market, paths, settings, strategies, tradelog
from app.routine import DayData, LogAlerter, OrbDay
from app.scheduler import RealClock, SimClock, run_day, run_forever


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


def cmd_run(a) -> int:
    from alpaca.trading.client import TradingClient
    logs.setup()
    rules = settings.risk_rules()
    orb = strategies.load("orb")
    al = settings.alpaca_settings()
    calendar = market.AlpacaCalendar(TradingClient(al.api_key, al.secret_key, paper=True))
    trade_log = tradelog.TradeLog()
    alerter = LogAlerter()   # Discord arrives in 1a.6

    def make_day(day: str) -> OrbDay:
        return OrbDay(orb, rules, trade_log, source="live", day=day, alerter=alerter,
                      sec_user_agent=settings.sec_user_agent())

    try:
        asyncio.run(run_forever(make_day, calendar, RealClock()))
    except KeyboardInterrupt:
        logging.getLogger("app").info("Stopped by you (Ctrl-C)")
    return 0


def cmd_replay(a) -> int:
    logs.setup()
    rules = settings.risk_rules()
    orb = strategies.load("orb")
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
                           timemachine_dir=Path(a.timemachine_dir) if a.timemachine_dir else None)
    focus = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None
    if focus is None and day_data is None:
        print("A replay from Yahoo needs --symbols (the focus list can't be rebuilt for a past day).")
        return 1
    alerter = LogAlerter()
    day_bot = OrbDay(orb, rules, trade_log, source="replay", day=day.isoformat(), alerter=alerter,
                     runs_root=runs_root, day_data=day_data, sec_user_agent=settings.sec_user_agent())
    clock = SimClock(datetime.combine(day, dtime(7, 0), tzinfo=market.NY))
    asyncio.run(run_day(day_bot, session, clock, simulated=True, focus=focus))

    rows = trade_log.signals(run_id=day_bot.run_id)
    print(f"\nReplay of {day} (run {day_bot.run_id}, saved in {db.relative_to(paths.REPO_ROOT)}):")
    print(f"  focus list {len(day_bot.focus)} stocks, {len(rows)} signals")
    for r in rows:
        al = trade_log.alert(r["id"])
        what = "ALERT" if al and al["sent"] else f"held ({al['held_reason']})" if al else "?"
        print(f"  {r['trigger_time']}  {r['symbol']:<6} {r['status']:<8} entry {r['entry'] or 0:>8.2f}"
              f"  stop {r['stop'] or 0:>8.2f}  target {r['target'] or 0:>8.2f}  qty {r['qty'] or '-':>4}  {what}")
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
    r.add_argument("--symbols", help="comma-separated focus list (default: every ticker in --offline)")
    r.add_argument("--db", help="trade log file (default data/replays.db)")
    sub.add_parser("check", help="Alpaca + Discord connection check")
    a = p.parse_args(argv)
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
