"""One backtest run, start to finish:

    settings (+ --set overrides) -> data (cached) -> signals -> selection -> metrics + report
    -> saved: data/backtests.db (source = backtest) and data/backtests/run-<id>.md / .json

    python -m app backtest --from 2024-11-01 --to 2026-11-17 --label baseline
    python -m app backtest --from 2024-11-01 --to 2026-11-17 --set exit.target=1R --label "1R target"
"""

from __future__ import annotations

import copy
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app import paths, settings, strategies, tradelog
from app.backtest import data, report, signals
from app.backtest.select import Rules, select

log = logging.getLogger(__name__)
DB = paths.SHARED_DATA_DIR / "backtests.db"
REPORTS = paths.SHARED_DATA_DIR / "backtests"


def apply_overrides(strategy_settings: dict, risk: dict, overrides: list[str]) -> tuple[dict, dict, dict]:
    """["exit.target=1R", "risk.max_trades_per_day=2", "selection.cash_limit=false"]
    -> (strategy settings, risk rules, selection options). Values are read as JSON when they can be."""
    s, r, sel = copy.deepcopy(strategy_settings), copy.deepcopy(risk), {"cash_limit": True}
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"--set wants key=value, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        parts = key.strip().split(".")
        target = r if parts[0] == "risk" else sel if parts[0] == "selection" else s
        if parts[0] in ("risk", "selection"):
            parts = parts[1:]
        node = target
        for p in parts[:-1]:
            if p not in node or not isinstance(node[p], dict):
                raise ValueError(f"unknown setting {key!r}")
            node = node[p]
        if parts[-1] not in node and target is not sel:
            raise ValueError(f"unknown setting {key!r}")
        node[parts[-1]] = value
    return s, r, sel


@dataclass
class RunResult:
    run_id: int
    label: str
    report_path: Path
    headline: dict
    views: dict
    baseline: tuple | None


def run(start: date, end: date, *, label: str, overrides: list[str] = (), db_path: Path = DB,
        progress=print, strategy_id: str = "orb") -> RunResult:
    strat = strategies.load(strategy_id)
    s, risk, sel = apply_overrides(strat.settings, settings.risk_rules(), list(overrides))
    cost = s.get("costs", {}).get("pct_per_side", 0.0)

    data.prepare(start, end, s["focus_list"], progress=progress)
    sessions = data.calendar(start, end)
    focus = lambda ss: json.loads((data.FOCUS_DIR / f"{ss.day}.json").read_text())["symbols"]
    bars = lambda ss, f: data.day_bars(ss.day, f, fetch=False)
    sigs = signals.generate(sessions, focus, bars, s, risk, cost_pct=cost, progress=progress)

    rules = Rules.from_settings(s, risk, cash_limit=bool(sel.get("cash_limit", True)))
    decisions = select(sigs, rules)
    traded = [d.signal for d in decisions if d.taken]
    every = [x for x in sigs if x.status == "pass"]
    other = Rules.from_settings(s, risk, cash_limit=not rules.cash_limit)
    other_traded = [d.signal for d in select(sigs, other) if d.taken]
    head = f"As traded (cap {rules.alert_cap} FCFS + risk rules, cash limit {'on' if rules.cash_limit else 'off'})"
    views = {head: report.metrics(traded),
             f"Same, cash limit {'off' if rules.cash_limit else 'on'}": report.metrics(other_traded),
             "Every signal taken": report.metrics(every)}

    log_db = tradelog.TradeLog(db_path)
    snapshot = {"strategy": s, "risk": risk, "selection": {**sel, **rules.__dict__}, "overrides": list(overrides)}
    run_id = log_db.start_run(strategy_id, "backtest", snapshot, label=label, date_from=start.isoformat(),
                              date_to=end.isoformat())
    log_db.save_backtest(run_id, decisions)
    log_db.finish_run(run_id)
    code = log_db.run(run_id)["code_version"] or "unknown"

    baseline = None
    REPORTS.mkdir(parents=True, exist_ok=True)
    for b in reversed(log_db.runs(strategy=strategy_id, source="backtest")):
        bj = REPORTS / f"run-{b['id']}.json"
        if b["id"] != run_id and (b["label"] or "").lower() == "baseline" and bj.exists():
            baseline = (b["id"], b["label"], json.loads(bj.read_text())["headline"])
            break
    log_db.close()

    w = s.get("scan_window", {"start": "?", "end": "?"})
    settings_line = (f"**{start} → {end}** ({len(sessions)} market days) · focus top {s['focus_list']['top_n_by_dollar_volume']}"
                     f" + {s['focus_list']['max_daily_scan_hits']} daily-scan hits · window {w['start']}–{w['end']} · "
                     f"volume ≥ {s.get('min_volume_x') or 'off'}× · stop {s.get('exit', {}).get('stop', '?')} · target {s.get('exit', {}).get('target', '?')} · "
                     f"cap {rules.alert_cap} FCFS · max {rules.max_trades} trades/day · daily loss ${rules.max_daily_loss:,.0f} · "
                     f"cash limit {'on' if rules.cash_limit else 'off'} · costs {cost * 100:.2f}%/side · "
                     f"${risk['budget']:,} account, ${risk['max_loss_per_trade_usd']} max loss"
                     + (f" · overrides: {', '.join(overrides)}" if overrides else ""))
    why_not = Counter(d.why for d in decisions if not d.taken)
    md = report.render(run_id=run_id, label=label, tag=strat.tag, settings_line=settings_line, code=code, views=views,
                       traded=traded, every=every, why_not=why_not, baseline=baseline)
    path = REPORTS / f"run-{run_id}.md"
    path.write_text(md)
    (REPORTS / f"run-{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "label": label, "from": start.isoformat(), "to": end.isoformat(),
         "created": datetime.now().isoformat(timespec="seconds"), "settings": snapshot, "code": code,
         "headline": views[head], "views": views}, indent=2, default=str))
    return RunResult(run_id, label, path, views[head], views, baseline)
