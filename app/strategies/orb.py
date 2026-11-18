"""The ORB bot's brain: opening range breakout, long only (Step 2b.1 moved it here, unchanged).

Every piece is the code the ORB bot has run since Step 1a/1b, wrapped behind the Brain contract:
    schedule     8:30 AM focus list; checks 1 minute after each 5-minute bar, 9:50–11:30 AM ET
    watchlist    top 150 most traded over $5 + up to 50 daily-scan hits (market.build_focus_list;
                 backtest: backtest.data.focus_for, the same rules on past data)
    candidates   the skill's ORB scan (scan.py orb): charts that closed above their opening range
    decide       app.engine.decide: the skill's entry.evaluate, exit.compute and size.size_trade
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

from app import engine, market
from app.market import Session
from app.strategies.base import Brain


class OrbBrain(Brain):
    id = "orb"
    tag = "ORB"

    def check_times(self, session: Session) -> list[datetime]:
        return market.check_times(session, self.s)

    def backtest_check_time(self, session: Session) -> datetime:
        return engine.window_end_check(session, self.s)

    def watchlist_live(self, workdir: Path) -> tuple[list[str], str]:
        doc = market.build_focus_list(self.s["focus_list"], workdir / "focus.json")
        return doc["symbols"], (f"focus list: {len(doc['top'])} most traded + {len(doc['daily_hits'])} daily-scan "
                                f"hits (closes through {doc['closes_through']}, {doc['seconds']}s)")

    def watchlist_history(self, day, store) -> list[str]:
        from app.backtest import data
        return data.focus_for(day, store, self.s["focus_list"])["symbols"]

    def candidates(self, symbols, now, workdir, rules, offline_bars=None):
        """The repo's ORB scan. Returns (symbols in trigger order, note if it couldn't run)."""
        folder = workdir / "_scan"
        (folder / "trader").mkdir(parents=True, exist_ok=True)
        (folder / "trader" / "config.json").write_text(json.dumps(rules))
        args = [sys.executable, str(market.SCAN_PY), "orb", "--symbols", ",".join(symbols),
                "--json", "--no-write", "--max-confirm", "0",
                "--or-minutes", str(self.s["opening_range_minutes"]),
                "--min-price", str(self.s["focus_list"]["min_price"])]
        if now:
            args += ["--now", now]
        if offline_bars:
            args += ["--offline", str(offline_bars)]
        p = subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=600)
        try:
            doc = json.loads(p.stdout)
        except json.JSONDecodeError:
            return [], (p.stderr.strip() or p.stdout.strip() or "scan failed").splitlines()[-1]
        hits = sorted(doc.get("hits", []), key=lambda h: (h.get("bar_index", 0), h["symbol"]))  # trigger order
        return [h["symbol"] for h in hits], None

    def decide(self, symbol, chart, session, now, rules, flat_by=None):
        return engine.decide(symbol, chart, session, now, self.s, rules, flat_by=flat_by)
