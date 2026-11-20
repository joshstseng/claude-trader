"""Mr. S backtests (plans/mrs-strategy.md): NQ 5m bars -> every session -> saved run -> #backtests (by Uri).

    python -m app backtest --strategy mrs --from 2026-09-14 --to 2026-11-20 --label baseline
    python -m app backtest --strategy mrs --from … --to … --set filters.adx_min=25 --label "ADX 25"
    python -m app backtest --strategy mrs --from 2021-11-01 --to … --set data_source=dukascopy --label …

Data: Yahoo's NQ=F (front month) 5m bars. Yahoo only serves the last ~60 days, so every run adds what it
fetches to a cache (data/bars/futures/), and history grows with each run. Older years: import later
(Databento). Runs share numbering and storage with every other backtest (data/backtests.db,
data/backtests/run-<id>.md / .json), so they stay repeatable and comparable.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import urllib.request
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import paths, settings, tradelog
from app.backtest.run import DB, REPORTS, apply_overrides
from app.strategies import mrs

log = logging.getLogger(__name__)
CACHE = paths.SHARED_DATA_DIR / "bars" / "futures"
WARMUP = timedelta(days=4)            # history before each session (covers a weekend) for RSI and ADX
SMALL_SAMPLE = 100
DATA_NOTE = "Yahoo NQ=F 5m (front month, cached)"


# ------------------------------------------------------------------------ data

def cache_path(symbol: str) -> Path:
    return CACHE / f"{symbol}-5m.json.gz"


def load_cache(symbol: str) -> list[mrs.Bar]:
    f = cache_path(symbol)
    if not f.exists():
        return []
    with gzip.open(f, "rt") as fh:
        rows = json.load(fh)
    return [mrs.Bar(datetime.fromtimestamp(r[0], timezone.utc), *r[1:]) for r in rows]


def save_cache(symbol: str, bars: list[mrs.Bar]) -> None:
    f = cache_path(symbol)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as fh:
        json.dump([[int(b.start.timestamp()), b.o, b.h, b.l, b.c, b.v] for b in bars], fh)
    tmp.replace(f)


def merge(old: list[mrs.Bar], new: list[mrs.Bar]) -> list[mrs.Bar]:
    by = {int(b.start.timestamp()): b for b in old}
    by.update({int(b.start.timestamp()): b for b in new})       # newer data wins
    return [by[k] for k in sorted(by)]


def parse_yahoo(doc: dict, now: datetime) -> list[mrs.Bar]:
    """Complete 5m bars only: drops the bar still forming and Yahoo's odd-timestamped last tick."""
    d = doc["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    out = []
    for t, o, h, l, c, v in zip(d.get("timestamp") or [], q["open"], q["high"], q["low"], q["close"], q["volume"]):
        if None in (o, h, l, c) or t % 300:
            continue
        start = datetime.fromtimestamp(t, timezone.utc)
        if start + mrs.FIVE > now:
            continue
        out.append(mrs.Bar(start, float(o), float(h), float(l), float(c), float(v or 0)))
    return out


def fetch_yahoo(symbol: str) -> list[mrs.Bar]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=60d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return parse_yahoo(json.load(r), datetime.now(timezone.utc))


def bars_for(symbol: str, *, fetch: bool = True, progress=print) -> list[mrs.Bar]:
    """The cache, topped up from Yahoo (a failed fetch falls back to the cache)."""
    bars = load_cache(symbol)
    if fetch:
        try:
            new = fetch_yahoo(symbol)
            bars = merge(bars, new)
            save_cache(symbol, bars)
            progress(f"{symbol}: fetched {len(new):,} bars; {len(bars):,} cached")
        except Exception as e:  # noqa: BLE001
            progress(f"{symbol}: couldn't fetch ({e}); using the cache ({len(bars):,} bars)")
    return bars


# ------------------------------------------------------------------------ running it

def run_sessions(bars: list[mrs.Bar], start: date, end: date, s: dict) -> list[mrs.SessionResult]:
    """Every session that starts on a day from start to end (Pacific dates) and has bars."""
    times = [b.start for b in bars]
    out, day = [], start
    while day <= end:
        st, en = mrs.session_bounds(day, s)
        i, j = bisect_left(times, st - WARMUP), bisect_left(times, en)
        k = bisect_left(times, st)
        if k < j:                                          # the market was open
            out.append(mrs.run_session(bars[i:j], day, s))
        day += timedelta(days=1)
    return out


def _why(text: str) -> str:
    """Skip reasons grouped: 'ADX 18.2 ≤ 20 (choppy)' -> 'ADX ≤ 20 (choppy)'."""
    if text.startswith(("ADX", "RSI")):
        word, _, rest = text.partition(" ")
        return word + " " + " ".join(x for x in rest.split(" ")[1:])
    return text.split(" (")[0]


def headline(sessions: list[mrs.SessionResult], s: dict) -> dict:
    trades = [t for x in sessions for t in x.trades]
    n = len(trades)
    pnl = [t.pnl_usd for t in trades]
    peak = dd = run = 0.0
    for p in pnl:
        run += p
        peak = max(peak, run)
        dd = min(dd, run - peak)
    by_session = [x.pnl_usd for x in sessions if x.trades]
    m = {
        "sessions": len(sessions), "sessions_traded": len(by_session), "trades": n,
        "longs": sum(t.side == "long" for t in trades), "shorts": sum(t.side == "short" for t in trades),
        "wins": sum(p > 0 for p in pnl), "results": dict(Counter(t.result for t in trades)),
        "skips": dict(Counter(_why(k["why"]) for x in sessions for k in x.skipped).most_common()),
        "stopped_for_loss": sum(x.stopped_for_loss for x in sessions),
        "stopped_for_win": sum(x.stopped_for_win for x in sessions),
        "account_usd": s["account"]["size_usd"],
    }
    if n:
        gross = sum(t.pnl_usd + t.cost_usd for t in trades)
        risk = sum(abs(t.entry - t.stop) * s["contract"]["point_value"] * t.contracts for t in trades)
        m.update({
            "win_rate": m["wins"] / n, "avg_r": sum(t.r for t in trades) / n, "total_r": sum(t.r for t in trades),
            "avg_r_gross": gross / risk if risk else 0.0, "total_usd": sum(pnl), "costs_usd": sum(t.cost_usd for t in trades),
            "max_dd_usd": dd, "avg_contracts": sum(t.contracts for t in trades) / n,
            "avg_stop_pts": sum(abs(t.entry - t.stop) for t in trades) / n,
            "avg_risk_usd": risk / n,
            "best_session_usd": max(by_session), "worst_session_usd": min(by_session),
        })
    return m


@dataclass
class MrsRun:
    run_id: int
    label: str
    report_path: Path
    headline: dict


def run(start: date, end: date, *, label: str, overrides: list[str] = (), db_path: Path = DB,
        reports: Path = REPORTS, fetch: bool = True, bars: list[mrs.Bar] | None = None, progress=print) -> MrsRun:
    base = json.loads((paths.STRATEGY_CONFIG_DIR / "mrs.json").read_text())
    s, _, _ = apply_overrides(base, {}, list(overrides))
    source = s.get("data_source", "yahoo")
    if bars is None and source == "dukascopy":
        from app.backtest import dukascopy
        bars = dukascopy.bars_5m(start - WARMUP - timedelta(days=1), end + timedelta(days=1), fetch=fetch,
                                 progress=progress)
    elif bars is None:
        bars = bars_for(s["data_symbol"], fetch=fetch, progress=progress)
    if not bars:
        raise RuntimeError(f"No bars for {start} → {end} ({source}).")
    first = bars[0].start.astimezone(mrs.PT).date()
    sessions = run_sessions(bars, max(start, first), end, s)
    m = headline(sessions, s)
    if source == "dukascopy":
        from app.backtest.dukascopy import NOTE as note
    else:
        note = DATA_NOTE
    snapshot = {"strategy": s, "overrides": list(overrides), "data": note,
                "bars": [bars[0].start.isoformat(), bars[-1].start.isoformat(), len(bars)]}
    log_db = tradelog.TradeLog(db_path)
    try:
        run_id = log_db.start_run("mrs", "backtest", snapshot, label=label,
                                  date_from=start.isoformat(), date_to=end.isoformat())
        log_db.finish_run(run_id)
        code = log_db.run(run_id)["code_version"]
    finally:
        log_db.close()
    doc = {"run_id": run_id, "label": label, "from": start.isoformat(), "to": end.isoformat(),
           "first_session": sessions[0].day if sessions else None, "last_session": sessions[-1].day if sessions else None,
           "code": code, "settings": snapshot, "headline": m,
           "trades": [dict(t.as_dict(), day=x.day) for x in sessions for t in x.trades]}
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"run-{run_id}.json").write_text(json.dumps(doc, indent=1))
    md = reports / f"run-{run_id}.md"
    md.write_text(report_md(doc))
    return MrsRun(run_id, label, md, m)


# ------------------------------------------------------------------------ report + post

def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def _r(x: float) -> str:
    return f"{x:+.3f}R".replace("-", "−")


def _day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%b %-d, %Y")


def find_baseline(run_id: int, reports: Path = REPORTS) -> dict | None:
    best = None
    for f in reports.glob("run-*.json"):
        r = json.loads(f.read_text())
        sid = ((r.get("settings") or {}).get("strategy") or {}).get("id")
        if sid == "mrs" and (r.get("label") or "").lower() == "baseline" and r["run_id"] != run_id:
            if best is None or r["run_id"] > best["run_id"]:
                best = r
    return best


def _r2(x: float) -> str:
    return f"{x:+.2f}R".replace("-", "−")


def _skips(skips: dict) -> str:
    """Grouped for reading: the two RSI sides count as one."""
    out: Counter = Counter()
    for k, v in skips.items():
        out["RSI" if k.startswith("RSI") else k.split(" (")[0]] += v
    return " · ".join(f"{k} ({v})" for k, v in out.most_common(3))


def _hours(start: str, end: str) -> str:
    """'16:00', '22:00' -> '4–10 PM'."""
    def h(x):
        t = datetime.strptime(x, "%H:%M")
        return t.strftime("%-I:%M").replace(":00", ""), t.strftime("%p")
    (a, pa), (b, pb) = h(start), h(end)
    return f"{a}–{b} {pb}" if pa == pb else f"{a} {pa}–{b} {pb}"


def summary(doc: dict, baseline: dict | None = None) -> str:
    """The #backtests message: the result first, a few short lines, the fine print small."""
    m, s = doc["headline"], doc["settings"]["strategy"]
    sess = s["session"]
    period = (f"{_day(doc['first_session'])} → {_day(doc['last_session'])}" if doc.get("first_session")
              else f"{_day(doc['from'])} → {_day(doc['to'])}")
    lines = [f"## 🧪 Mr. S · Backtest #{doc['run_id']} · {doc['label']}",
             f"-# {sess['name']} {_hours(sess['start'], sess['end'])} PT · {period} · {m['sessions']} sessions"]
    if not m["trades"]:
        lines.append("No trades.")
    else:
        res = m["results"]
        icon = "📈" if m["total_usd"] > 0 else "📉"
        lines += [
            "",
            f"{icon} **{_usd(m['total_usd'])}**  ·  {_r2(m['avg_r'])} a trade  ·  "
            f"{m['trades']} trades  ·  {m['win_rate'] * 100:.0f}% win",
            "",
            f"**Exits** 🎯 {res.get('2R', 0)} at 2R · ↩️ {res.get('middle', 0)} middle · ❌ {res.get('stop', 0)} stop"
            + (f" · ⚖️ {res['be_stop']} break-even" if res.get("be_stop") else "")
            + (f" · 🔒 {res['lock_stop']} locked +1R" if res.get("lock_stop") else "")
            + (f" · ⏰ {res['session_end']} at close" if res.get("session_end") else ""),
            f"**Sides** {m['longs']} long · {m['shorts']} short",
            f"**Risk** ~{_usd(m.get('avg_risk_usd', 0)).lstrip('+')} a trade · worst drawdown {_usd(m['max_dd_usd'])}",
        ]
        if baseline and baseline["headline"].get("trades"):
            bm = baseline["headline"]
            diff = m["avg_r"] - bm["avg_r"]
            arrow = "▲" if diff > 0 else "▼" if diff < 0 else "="
            dt = m["trades"] - bm["trades"]
            lines.append(f"**vs baseline #{baseline['run_id']}** {arrow} {_r2(diff)} a trade · "
                         f"{_usd(m['total_usd'] - bm['total_usd'])} · "
                         + (f"{abs(dt)} {'more' if dt > 0 else 'fewer'} trades" if dt else "same trades"))
    lines.append("")
    if doc["settings"].get("overrides"):
        lines.append(f"-# Changed: {', '.join(doc['settings']['overrides'])}")
    if m.get("skips"):
        lines.append(f"-# Skipped: {_skips(m['skips'])}")
    fine = []
    if m["trades"]:
        fine.append(f"costs {_usd(-m['costs_usd'])}")
        if m["trades"] < SMALL_SAMPLE:
            fine.append(f"⚠️ {m['trades']} trades is too few to judge")
    fine += [doc["settings"]["data"], f"code {doc.get('code', '?')}"]
    lines.append("-# " + " · ".join(fine))
    return "\n".join(lines)


def report_md(doc: dict) -> str:
    m = doc["headline"]
    text = "\n".join(x[3:] if x.startswith("-# ") else x for x in summary(doc).replace("**", "").splitlines()[1:])
    out = [f"# Mr. S backtest #{doc['run_id']}: {doc['label']}", "", text, "",
           "## Settings", "```json", json.dumps(doc["settings"]["strategy"], indent=1), "```", ""]
    if m.get("skips"):
        out += ["## Setups skipped", "| Why | Count |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in m["skips"].items()]
        out.append("")
    out += ["## Trades (Pacific time)",
            "| Session | Side | Cross | Entry | In | Stop | 2R | Mid | MNQ | RSI | ADX | Out | Exit | Result | R | $ |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in doc["trades"]:
        out.append(f"| {t['day']} | {t['side']} | {t['cross_at'][11:16]} | {t['entry_at'][11:16]} | {t['entry']} | "
                   f"{t['stop']} | {t['target_2r']} | {t['middle_at_entry']} | {t['contracts']} | {t.get('rsi', t.get('rsi15'))} | "
                   f"{t.get('adx', t.get('adx15'))} | {(t['exit_at'] or '')[11:16]} | {t['exit']} | {t['result']} | {t['r']:+.2f} | "
                   f"{t['pnl_usd']:+,.0f} |")
    return "\n".join(out) + "\n"


def post(run_id: int, reports: Path = REPORTS) -> bool:
    """Uri (the head bot) posts Mr. S's run to #backtests while Mr. S has no Discord bot of his own.
    False if #backtests isn't set up."""
    import dataclasses
    channel = settings.discord_backtests_channel()
    if channel is None:
        return False
    from app.discord_bot import post_once
    doc = json.loads((reports / f"run-{run_id}.json").read_text())
    cfg = settings.discord_settings()
    token = (os.environ.get("DISCORD_BOT_TOKEN_HEAD") or os.environ.get("DISCORD_BOT_TOKEN_MRS") or "").strip()
    if token:
        cfg = dataclasses.replace(cfg, bot_token=token)
    asyncio.run(post_once(cfg, channel, [(summary(doc, find_baseline(run_id, reports)), None, None)],
                          files=[reports / f"run-{run_id}.md"]))
    return True
