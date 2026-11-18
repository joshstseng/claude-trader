"""Post a backtest run's summary to #backtests, with the full report attached."""

from __future__ import annotations

import asyncio
import json
from datetime import date

from app import settings
from app.backtest.run import REPORTS


def _r(x: float) -> str:
    return f"{x:+.3f}R".replace("-", "−")


def _usd(x: float, cents: bool = False) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.{2 if cents else 0}f}"


def _day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%b %-d, %Y")


def summary(run: dict, baseline: dict | None, show_tag: bool = False) -> str:
    """The #backtests message for one run (run / baseline = the run-<id>.json contents).
    show_tag: the poster isn't this strategy's own bot, so say which strategy it is ([DEMO] …)."""
    m = run["headline"]
    from app.strategies import tag_for
    sid = ((run.get("settings") or {}).get("strategy") or {}).get("id", "orb")
    head = (f"**[{tag_for(sid)}] Backtest #{run['run_id']}: {run['label']}**" if show_tag
            else f"**Backtest #{run['run_id']}: {run['label']}**")
    period = f"{_day(run['from'])} → {_day(run['to'])}"
    if not m.get("trades"):
        return f"{head}\n{period} · no trades."
    lines = [
        head,
        f"{period} · {m['trades']:,} trades · win rate {m['win_rate'] * 100:.0f}% · "
        f"**{_r(m['avg_r'])} a trade** ({_usd(m['avg_usd'], cents=True)}) · total **{_usd(m['total_usd'])}** · "
        f"worst drawdown {_usd(m['max_dd_usd'])}",
        f"✅ {m['target']:,} target · ❌ {m['stop']:,} stop · ➖ {m['flat']:,} flat · before costs {_r(m['avg_r_gross'])}",
    ]
    overrides = run.get("settings", {}).get("overrides") or []
    if overrides:
        lines.append(f"Changed: `{'`, `'.join(overrides)}`")
    if baseline and baseline["run_id"] != run["run_id"] and baseline["headline"].get("trades"):
        b = baseline["headline"]
        diff = m["avg_r"] - b["avg_r"]
        word = "better" if diff > 0 else "worse" if diff < 0 else "the same"
        lines.append(f"vs baseline (#{baseline['run_id']}): **{_r(diff)} a trade {word}** · "
                     f"total {_usd(m['total_usd'] - b['total_usd'])} · trades {m['trades'] - b['trades']:+,}")
    verdict = "📈 has an edge after costs" if m["avg_r"] > 0 else "📉 loses money after costs"
    lines.append(f"{verdict} · full report attached · code `{run.get('code', '?')}`")
    return "\n".join(lines)


def load(run_id: int) -> dict:
    return json.loads((REPORTS / f"run-{run_id}.json").read_text())


def _sid(run: dict) -> str:
    return ((run.get("settings") or {}).get("strategy") or {}).get("id", "orb")


def find_baseline(run_id: int) -> dict | None:
    """The latest run labeled 'baseline' (other than this one) for the same strategy."""
    best = None
    this = REPORTS / f"run-{run_id}.json"
    sid = _sid(json.loads(this.read_text())) if this.exists() else "orb"
    for f in REPORTS.glob("run-*.json"):
        r = json.loads(f.read_text())
        if (r.get("label") or "").lower() == "baseline" and r["run_id"] != run_id and _sid(r) == sid:
            if best is None or r["run_id"] > best["run_id"]:
                best = r
    return best


def poster_for(strategy_id: str) -> tuple[str | None, bool]:
    """Which Discord bot posts a strategy's backtests: (its token or None for the default, is it the
    strategy's own bot). Each bot posts its own when DISCORD_BOT_TOKEN_<ID> is in .env (e.g.
    DISCORD_BOT_TOKEN_DEMO); otherwise the default bot (DISCORD_BOT_TOKEN, the one STRATEGY names,
    ORB by default) posts, and tags other strategies' runs."""
    import os
    own = os.environ.get(f"DISCORD_BOT_TOKEN_{strategy_id.upper()}", "").strip()
    if own:
        return own, True
    default = (os.environ.get("STRATEGY", "orb").strip().lower() or "orb")
    return None, strategy_id == default


def post(run_id: int) -> bool:
    """Post run `run_id` to #backtests as the strategy's own bot when it has one. False if the
    channel isn't set up."""
    import dataclasses
    channel = settings.discord_backtests_channel()
    if channel is None:
        return False
    from app.discord_bot import post_once
    run = load(run_id)
    token, own = poster_for(_sid(run))
    cfg = settings.discord_settings()
    if token:
        cfg = dataclasses.replace(cfg, bot_token=token)
    text = summary(run, find_baseline(run_id), show_tag=not own)
    asyncio.run(post_once(cfg, channel, [(text, None, None)], files=[REPORTS / f"run-{run_id}.md"]))
    return True
