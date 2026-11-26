"""Save a scalp research run under the shared backtest numbering and post it to #backtests (as Uri)."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path

from app import settings, tradelog
from app.backtest.run import DB, REPORTS


def save_and_post(label: str, start: str, end: str, settings_doc: dict, summary: str, report_md: str,
                  post: bool = True) -> int:
    log = tradelog.TradeLog(DB)
    try:
        run_id = log.start_run("scalp", "backtest", {"strategy": {"id": "scalp", **settings_doc}}, label=label,
                               date_from=start, date_to=end)
        log.finish_run(run_id)
        code = log.run(run_id)["code_version"]
    finally:
        log.close()
    REPORTS.mkdir(parents=True, exist_ok=True)
    head = f"## 🔬 Scalp research · Backtest #{run_id} · {label}"
    text = f"{head}\n{summary}\n-# research only, not a live bot · code {code}"
    (REPORTS / f"run-{run_id}.json").write_text(json.dumps({"run_id": run_id, "label": label, "from": start, "to": end,
                                                            "code": code, "settings": settings_doc}, indent=1))
    path = REPORTS / f"run-{run_id}.md"
    path.write_text(f"# Scalp research, backtest #{run_id}: {label}\n\n{report_md}\n")
    if post:
        channel = settings.discord_backtests_channel()
        if channel is None:
            raise RuntimeError("DISCORD_CHANNEL_BACKTESTS isn't set")
        from app.discord_bot import post_once
        cfg = settings.discord_settings()
        token = (os.environ.get("DISCORD_BOT_TOKEN_HEAD") or "").strip()
        if token:
            cfg = dataclasses.replace(cfg, bot_token=token)
        asyncio.run(post_once(cfg, channel, [(text[:1990], None, None)], files=[Path(path)]))
    return run_id
