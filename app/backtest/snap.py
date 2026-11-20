"""Snap backtests (app/strategies/snap.py) on Alpaca daily bars (dividend-adjusted, cached in data/bars/lab/1d).

    python -m app backtest --strategy snap --from 2016-01-01 --to 2026-10-31 --label baseline
    python -m app backtest --strategy snap --from … --to … --set entry.rsi_below=5 --label "RSI under 5"

Same run numbering and storage as every backtest; Uri posts each run to #backtests.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from app import paths, settings, tradelog
from app.backtest.run import DB, REPORTS, apply_overrides
from app.research import data
from app.research.evaluate import Trade, verdict
from app.strategies import snap

NOTE = "Alpaca daily bars (SIP, dividend-adjusted) · fills at the close"


@dataclasses.dataclass
class SnapRun:
    run_id: int
    label: str
    report_path: Path
    headline: dict


def headline(trades: list[snap.SnapTrade], s: dict) -> dict:
    n = len(trades)
    m = {"trades": n, "days": len({t.day_in for t in trades}), "wins": sum(t.pnl_usd > 0 for t in trades)}
    if n:
        win = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
        loss = -sum(t.pnl_usd for t in trades if t.pnl_usd <= 0)
        run = peak = dd = 0.0
        years: dict = defaultdict(float)
        for t in sorted(trades, key=lambda x: x.day_out):
            run += t.pnl_usd
            peak = max(peak, run)
            dd = min(dd, run - peak)
            years[t.day_out[:4]] += t.pnl_usd
        m.update(win_rate=m["wins"] / n, avg_r=sum(t.r for t in trades) / n, total_usd=run,
                 profit_factor=win / loss if loss else None, max_dd_usd=dd, years=dict(sorted(years.items())),
                 stops=sum(t.why_out == "stop" for t in trades))
    return m


def _as_lab(trades: list[snap.SnapTrade]) -> list[Trade]:
    d = lambda x: datetime.fromisoformat(x)                                       # noqa: E731
    return [Trade(t.sym, 1, d(t.day_in), d(t.day_out), t.entry, t.exit, t.shares) for t in trades]


def run(start: date, end: date, *, label: str, overrides=(), db_path: Path = DB, reports: Path = REPORTS,
        fetch: bool = True, progress=print) -> SnapRun:
    base = json.loads((paths.STRATEGY_CONFIG_DIR / "snap.json").read_text())
    s, _, _ = apply_overrides(base, {}, list(overrides))
    trades: list[snap.SnapTrade] = []
    for sym in s["universe"]:
        bars = data.daily(sym, fetch=fetch)
        trades += [t for t in snap.run_symbol(sym, bars, s) if start.isoformat() <= t.day_in <= end.isoformat()]
    trades.sort(key=lambda t: (t.day_in, t.sym))
    m = headline(trades, s)
    ok, v = verdict(_as_lab(trades))
    m["bar"] = {k: bool(x) for k, x in v["checks"].items()}
    snapshot = {"strategy": s, "overrides": list(overrides), "data": NOTE}
    log_db = tradelog.TradeLog(db_path)
    try:
        run_id = log_db.start_run("snap", "backtest", snapshot, label=label, date_from=start.isoformat(),
                                  date_to=end.isoformat())
        log_db.finish_run(run_id)
        code = log_db.run(run_id)["code_version"]
    finally:
        log_db.close()
    doc = {"run_id": run_id, "label": label, "from": start.isoformat(), "to": end.isoformat(), "code": code,
           "settings": snapshot, "headline": m, "trades": [t.as_dict() for t in trades]}
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"run-{run_id}.json").write_text(json.dumps(doc, indent=1))
    path = reports / f"run-{run_id}.md"
    path.write_text(report_md(doc))
    return SnapRun(run_id, label, path, m)


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def summary(doc: dict) -> str:
    m = doc["headline"]
    lines = [f"## 🫰 Snap · index ETF dip-buyer · Backtest #{doc['run_id']} · {doc['label']}",
             f"-# QQQ · SPY · IWM · DIA · {doc['from']} → {doc['to']} · daily, buys dips in uptrends"]
    if not m["trades"]:
        return "\n".join(lines + ["No trades."])
    icon = "📈" if m["total_usd"] > 0 else "📉"
    pf = f"{m['profit_factor']:.2f}" if m.get("profit_factor") else "∞"
    lines += ["", f"{icon} **{_usd(m['total_usd'])}**  ·  PF {pf}  ·  {m['trades']} trades  ·  "
                  f"{m['win_rate'] * 100:.0f}% win  ·  worst drawdown {_usd(m['max_dd_usd'])}",
              "**By year** " + " · ".join(f"{y}: {_usd(p)}" for y, p in m["years"].items()),
              f"**Stops hit** {m['stops']}",
              "**Bar** " + " · ".join(f"{'✓' if ok else '✗'} {k}" for k, ok in m["bar"].items()), ""]
    if doc["settings"].get("overrides"):
        lines.append(f"-# Changed: {', '.join(doc['settings']['overrides'])}")
    lines.append(f"-# $50k · 1% risk to a 3×ATR stop · after 1 bp costs · {NOTE} · code {doc.get('code', '?')}")
    return "\n".join(lines)


def report_md(doc: dict) -> str:
    out = [f"# Snap, backtest #{doc['run_id']}: {doc['label']}", "",
           "\n".join(x[3:] if x.startswith("-# ") else x for x in summary(doc).replace("**", "").splitlines()[1:]), "",
           "## Settings", "```json", json.dumps(doc["settings"]["strategy"], indent=1), "```", "",
           "## Trades", "| In | Out | ETF | Why | Entry | Stop | Exit | Shares | Out because | $ | R |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in doc["trades"]:
        out.append(f"| {t['day_in']} | {t['day_out']} | {t['sym']} | {t['why_in']} | {t['entry']:.2f} | {t['stop']:.2f} | "
                   f"{t['exit']:.2f} | {t['shares']:.0f} | {t['why_out']} | {t['pnl_usd']:+,.0f} | {t['r']:+.2f} |")
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
    asyncio.run(post_once(cfg, channel, [(summary(doc), None, None)], files=[reports / f"run-{run_id}.md"]))
    return True
