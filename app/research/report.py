"""Save and post research-lab runs: same run numbering and folder as every backtest (data/backtests.db,
data/backtests/run-N.json/.md); Uri posts the summary to #backtests."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os

from app import settings, tradelog
from app.backtest.run import DB, REPORTS
from app.research.evaluate import Trade, verdict


def _k(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def summary(run_id: int, title: str, label: str, trades: list[Trade], note: str, show_test: bool) -> str:
    ok, v = verdict(trades)
    tr, te, al, pre = v["train"], v["test"], v["all"], v["before"]
    lines = [f"## 🧪 Lab · {title} · Backtest #{run_id} · {label}", f"-# {note}", "",
             f"**Built on 2021–2023** {_k(tr.pnl)} · PF {tr.pf:.2f} · {tr.n} trades · {tr.win_rate * 100:.0f}% win · "
             f"worst drawdown {_k(tr.max_dd)}"]
    if pre.n:
        lines.append(f"**Earlier history** {_k(pre.pnl)} · PF {pre.pf:.2f} · {pre.n} trades")
    if show_test:
        icon = "✅" if ok else "❌"
        lines += [f"**Untouched 2024–2026** {_k(te.pnl)} · PF {te.pf:.2f} · {te.n} trades",
                  "**By year** " + " · ".join(f"{y}: {_k(p)}" for y, p in al.years.items()),
                  f"**Bar** {icon} " + " · ".join(f"{'✓' if good else '✗'} {name}" for name, good in v["checks"].items())]
    lines.append("-# $50k account · after costs · research only, not trading")
    return "\n".join(lines)


def record(strategy_id: str, title: str, label: str, trades: list[Trade], settings_doc: dict, note: str,
           show_test: bool = True, post: bool = True) -> int:
    db = tradelog.TradeLog(DB)
    try:
        run_id = db.start_run(strategy_id, "backtest", {"strategy": settings_doc, "data": note}, label=label,
                              date_from="2016-01-01", date_to="2026-10-31")
        db.finish_run(run_id)
    finally:
        db.close()
    ok, v = verdict(trades)
    text = summary(run_id, title, label, trades, note, show_test)
    rows = [dataclasses.asdict(t) | {"pnl": round(t.pnl, 2)} for t in trades]
    for r in rows:
        r["t_in"], r["t_out"] = r["t_in"].isoformat(), r["t_out"].isoformat()
    (REPORTS / f"run-{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "label": label, "settings": {"strategy": {"id": strategy_id, **settings_doc}, "data": note},
         "pass": ok, "trades": rows}, indent=1, default=str))
    md = text.replace("**", "").replace("-# ", "").replace("## ", "# ")
    md += "\n\n## Trades\n| In | Out | Side | Entry | Exit | Qty | P&L |\n|---|---|---|---|---|---|---|\n"
    md += "\n".join(f"| {r['t_in'][:16]} | {r['t_out'][:16]} | {'long' if r['side'] > 0 else 'short'} | "
                    f"{r['p_in']:.2f} | {r['p_out']:.2f} | {r['qty']:g} | {r['pnl']:+,.0f} |" for r in rows)
    (REPORTS / f"run-{run_id}.md").write_text(md + "\n")
    if post:
        settings.load_env()
        channel = settings.discord_backtests_channel()
        token = (os.environ.get("DISCORD_BOT_TOKEN_HEAD") or "").strip()
        if channel is not None and token:
            from app.discord_bot import post_once
            cfg = dataclasses.replace(settings.discord_settings(), bot_token=token)
            asyncio.run(post_once(cfg, channel, [(text, None, None)], files=[REPORTS / f"run-{run_id}.md"]))

    return run_id


def repost(run_id: int, title: str, note: str, show_test: bool = True) -> None:
    """Post a saved run again (e.g. after a posting failure)."""
    doc = json.loads((REPORTS / f"run-{run_id}.json").read_text())
    from datetime import datetime
    trades = [Trade(r["sym"], r["side"], datetime.fromisoformat(r["t_in"]), datetime.fromisoformat(r["t_out"]),
                    r["p_in"], r["p_out"], r["qty"], r["cost"], r.get("note", "")) for r in doc["trades"]]
    settings.load_env()
    channel = settings.discord_backtests_channel()
    token = (os.environ.get("DISCORD_BOT_TOKEN_HEAD") or "").strip()
    from app.discord_bot import post_once
    cfg = dataclasses.replace(settings.discord_settings(), bot_token=token)
    asyncio.run(post_once(cfg, channel, [(summary(run_id, title, doc["label"], trades, note, show_test), None, None)],
                          files=[REPORTS / f"run-{run_id}.md"]))
