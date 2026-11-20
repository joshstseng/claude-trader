"""Mr. S "8 AM retest" backtests (app/strategies/mrs8.py), on HistData's Nasdaq-100 1m bars.

    python -m app backtest --strategy mrs8 --from 2021-01-01 --to 2026-10-31 --label baseline
    python -m app backtest --strategy mrs8 --from … --to … --set trend_filter=1h --label "1h trend"

Same run numbering and storage as every backtest; Uri posts each run to #backtests.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from bisect import bisect_left
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from app import paths, settings, tradelog
from app.backtest import histdata
from app.backtest.mrs import _day, _r2, _usd, to_bars
from app.backtest.run import DB, REPORTS, apply_overrides
from app.strategies import mrs8

HISTORY = timedelta(days=5)          # 15m and 1h structure before each morning


def run_days(bars1, start: date, end: date, s: dict) -> list[mrs8.Day8]:
    times = [b.start for b in bars1]
    out, day = [], start
    while day <= end:
        if day.weekday() < 5:
            lo = datetime.combine(day, datetime.min.time(), tzinfo=mrs8.PT) - HISTORY
            hi = datetime.combine(day, datetime.min.time(), tzinfo=mrs8.PT) + timedelta(hours=10)
            chunk = bars1[bisect_left(times, lo):bisect_left(times, hi)]
            if any(b.start.astimezone(mrs8.PT).date() == day for b in chunk):
                out.append(mrs8.run_day(chunk, day, s))
        day += timedelta(days=1)
    return out


def headline(days: list[mrs8.Day8], s: dict) -> dict:
    T = [d.trade for d in days if d.trade]
    n = len(T)
    m = {"days": len(days), "trades": n, "longs": sum(t.side == "long" for t in T),
         "shorts": sum(t.side == "short" for t in T), "wins": sum(t.pnl_usd > 0 for t in T),
         "results": dict(Counter(t.result for t in T)),
         "skips": dict(Counter((d.why or "").split(" (")[0] for d in days if not d.trade).most_common()),
         "stop_from": dict(Counter(t.stop_from for t in T).most_common()),
         "target_from": dict(Counter("level" if "R)" in t.target_from else t.target_from for t in T).most_common()),
         "account_usd": s["account"]["size_usd"]}
    if n:
        pv = s["contract"]["point_value"]
        risk = sum(abs(t.entry - t.stop) * pv * t.contracts for t in T)
        run = peak = dd = 0.0
        for t in T:
            run += t.pnl_usd
            peak = max(peak, run)
            dd = min(dd, run - peak)
        m.update({"win_rate": m["wins"] / n, "avg_r": sum(t.r for t in T) / n, "total_r": sum(t.r for t in T),
                  "avg_r_gross": sum(t.pnl_usd + t.cost_usd for t in T) / risk, "total_usd": sum(t.pnl_usd for t in T),
                  "costs_usd": sum(t.cost_usd for t in T), "max_dd_usd": dd, "avg_risk_usd": risk / n,
                  "avg_stop_pts": sum(abs(t.entry - t.stop) for t in T) / n})
    return m


@dataclasses.dataclass
class Run8:
    run_id: int
    label: str
    report_path: Path
    headline: dict


def run(start: date, end: date, *, label: str, overrides=(), db_path: Path = DB, reports: Path = REPORTS,
        fetch: bool = True, bars1=None, progress=print) -> Run8:
    base = json.loads((paths.STRATEGY_CONFIG_DIR / "mrs8.json").read_text())
    s, _, _ = apply_overrides(base, {}, list(overrides))
    if bars1 is None:
        lo, hi = start - HISTORY - timedelta(days=1), end + timedelta(days=1)
        if fetch:
            histdata.download(lo, hi, progress=progress)
        bars1 = to_bars(histdata.load_1m(lo, hi))
    days = run_days(bars1, start, end, s)
    m = headline(days, s)
    snapshot = {"strategy": s, "overrides": list(overrides), "data": histdata.NOTE}
    log_db = tradelog.TradeLog(db_path)
    try:
        run_id = log_db.start_run("mrs8", "backtest", snapshot, label=label, date_from=start.isoformat(),
                                  date_to=end.isoformat())
        log_db.finish_run(run_id)
        code = log_db.run(run_id)["code_version"]
    finally:
        log_db.close()
    doc = {"run_id": run_id, "label": label, "from": start.isoformat(), "to": end.isoformat(),
           "first_day": days[0].day if days else None, "last_day": days[-1].day if days else None,
           "code": code, "settings": snapshot, "headline": m, "trades": [d.trade.as_dict() for d in days if d.trade]}
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"run-{run_id}.json").write_text(json.dumps(doc, indent=1))
    md = reports / f"run-{run_id}.md"
    md.write_text(report_md(doc))
    return Run8(run_id, label, md, m)


def find_baseline(run_id: int, reports: Path = REPORTS) -> dict | None:
    best = None
    for f in reports.glob("run-*.json"):
        r = json.loads(f.read_text())
        if (((r.get("settings") or {}).get("strategy") or {}).get("id") == "mrs8"
                and (r.get("label") or "").lower() == "baseline" and r["run_id"] != run_id):
            if best is None or r["run_id"] > best["run_id"]:
                best = r
    return best


def summary(doc: dict, baseline: dict | None = None) -> str:
    m = doc["headline"]
    period = f"{_day(doc['first_day'])} → {_day(doc['last_day'])}" if doc.get("first_day") else ""
    lines = [f"## 🧪 Mr. S · 8 AM retest · Backtest #{doc['run_id']} · {doc['label']}",
             f"-# NY AM · 8:00 ET candle, breakouts from 6:00 AM PT · {period} · {m['days']} days"]
    if not m["trades"]:
        lines.append("No trades.")
    else:
        res = m["results"]
        icon = "📈" if m["total_usd"] > 0 else "📉"
        lines += ["",
                  f"{icon} **{_usd(m['total_usd'])}**  ·  {_r2(m['avg_r'])} a trade  ·  {m['trades']} trades  ·  "
                  f"{m['win_rate'] * 100:.0f}% win",
                  "",
                  f"**Exits** 🎯 {res.get('target', 0)} target · ❌ {res.get('stop', 0)} stop · "
                  f"⏰ {res.get('session_end', 0)} at 9:00",
                  f"**Sides** {m['longs']} long · {m['shorts']} short",
                  f"**Risk** ~{_usd(m['avg_risk_usd']).lstrip('+')} a trade · avg stop {m['avg_stop_pts']:.1f} pts · "
                  f"worst drawdown {_usd(m['max_dd_usd'])}",
                  "**Stops from** " + " · ".join(f"{k} {v}" for k, v in m["stop_from"].items()),
                  "**Targets** " + " · ".join(f"{k} {v}" for k, v in m["target_from"].items())]
        if baseline and baseline["headline"].get("trades"):
            b = baseline["headline"]
            diff = m["avg_r"] - b["avg_r"]
            lines.append(f"**vs baseline #{baseline['run_id']}** {'▲' if diff > 0 else '▼' if diff < 0 else '='} "
                         f"{_r2(diff)} a trade · {_usd(m['total_usd'] - b['total_usd'])} · trades {m['trades'] - b['trades']:+d}")
    lines.append("")
    if doc["settings"].get("overrides"):
        lines.append(f"-# Changed: {', '.join(doc['settings']['overrides'])}")
    if m.get("skips"):
        lines.append("-# No trade: " + " · ".join(f"{k} ({v})" for k, v in list(m["skips"].items())[:4]))
    fine = [f"before costs {_r2(m['avg_r_gross'])}", f"costs {_usd(-m['costs_usd'])}"] if m["trades"] else []
    if m["trades"] and m["trades"] < 100:
        fine.append(f"⚠️ {m['trades']} trades is too few to judge")
    lines.append("-# " + " · ".join(fine + [doc["settings"]["data"], f"code {doc.get('code', '?')}"]))
    return "\n".join(lines)


def report_md(doc: dict) -> str:
    out = [f"# Mr. S 8 AM retest, backtest #{doc['run_id']}: {doc['label']}", "",
           "\n".join(x[3:] if x.startswith("-# ") else x for x in summary(doc).replace("**", "").splitlines()[1:]), "",
           "## Settings", "```json", json.dumps(doc["settings"]["strategy"], indent=1), "```", "",
           "## Trades (Pacific time)",
           "| Day | Side | Ref high | Ref low | Break | Filled | Entry | Stop | From | Target | From | MNQ | Out | Exit | Result | R | $ |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in doc["trades"]:
        out.append(f"| {t['day']} | {t['side']} | {t['ref_hi']} | {t['ref_lo']} | {t['break_at'][11:16]} | "
                   f"{t['entry_at'][11:16]} | {t['entry']} | {t['stop']} | {t['stop_from']} | {t['target']} | "
                   f"{t['target_from']} | {t['contracts']} | {(t['exit_at'] or '')[11:16]} | {t['exit']} | "
                   f"{t['result']} | {t['r']:+.2f} | {t['pnl_usd']:+,.0f} |")
    return "\n".join(out) + "\n"


def post(run_id: int, reports: Path = REPORTS) -> bool:
    channel = settings.discord_backtests_channel()
    if channel is None:
        return False
    from app.discord_bot import post_once
    doc = json.loads((reports / f"run-{run_id}.json").read_text())
    cfg = settings.discord_settings()
    token = (os.environ.get("DISCORD_BOT_TOKEN_HEAD") or "").strip()
    if token:
        cfg = dataclasses.replace(cfg, bot_token=token)
    asyncio.run(post_once(cfg, channel, [(summary(doc, find_baseline(run_id, reports)), None, None)],
                          files=[reports / f"run-{run_id}.md"]))
    return True
