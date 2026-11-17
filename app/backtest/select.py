"""Selection: which signals would actually have become trades.

Applied after the signals exist (so trying a new rule takes seconds), day by day, in trigger order:

  1. alerts   the first `alert_cap` tradable signals of the day are alerted (first come, first
              served, like the live bot); you approve every alert
  2. risk     each approved alert goes through the same daily rules as trader-risk:
                trades       at most `max_trades` entries a day
                daily loss   the max losses (at the stops) of today's entries + this one <= the limit
                cash         optional: the open positions' cost + this one must fit the account's cash
                             (no margin, keeping the cash buffer). Positions free their cash at exit.

Every signal gets a decision: "taken", or why not.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from app.backtest.signals import BtSignal


@dataclass(frozen=True)
class Rules:
    alert_cap: int = 5
    max_trades: int = 3
    max_daily_loss: float = 150.0
    cash_limit: bool = False
    cash_available: float = 4500.0   # budget minus the cash buffer

    @classmethod
    def from_settings(cls, strategy_settings: dict, risk: dict, *, cash_limit: bool = False) -> "Rules":
        budget = float(risk.get("budget") or 0)
        return cls(alert_cap=int(strategy_settings["alerts"]["max_per_day"]),
                   max_trades=int(risk.get("max_trades_per_day") or 0),
                   max_daily_loss=float(risk.get("max_daily_loss_usd") or 0),
                   cash_limit=cash_limit,
                   cash_available=round(budget * (1 - float(risk.get("cash_buffer_pct") or 0) / 100), 2))


@dataclass(frozen=True)
class Decision:
    signal: BtSignal
    alerted: bool
    taken: bool
    why: str            # "taken" or the reason it wasn't


def select(signals: list[BtSignal], rules: Rules) -> list[Decision]:
    """Signals must be in time order (as signals.generate returns them)."""
    out: list[Decision] = []
    for _, day_iter in groupby(signals, key=lambda s: s.day):
        alerts = trades = 0
        at_risk = 0.0
        open_pos: list[tuple[str, float]] = []          # (exit time, cost) of today's open trades
        for s in day_iter:
            if s.status != "pass":
                out.append(Decision(s, False, False, f"refused ({s.reason.split(':')[0]})"))
                continue
            if rules.alert_cap and alerts >= rules.alert_cap:
                out.append(Decision(s, False, False, f"not alerted: daily alert cap ({rules.alert_cap})"))
                continue
            alerts += 1
            if rules.max_trades and trades >= rules.max_trades:
                out.append(Decision(s, True, False, f"risk: max {rules.max_trades} trades a day"))
                continue
            if rules.max_daily_loss and at_risk + (s.max_loss or 0) > rules.max_daily_loss + 0.005:
                out.append(Decision(s, True, False, f"risk: daily loss limit (${rules.max_daily_loss:,.0f})"))
                continue
            if rules.cash_limit:
                open_pos = [(t, c) for t, c in open_pos if t > s.trigger_time]   # exited ones free their cash
                in_use = sum(c for _, c in open_pos)
                if in_use + (s.cost or 0) > rules.cash_available + 0.005:
                    out.append(Decision(s, True, False, "risk: not enough cash (positions still open)"))
                    continue
            trades += 1
            at_risk += s.max_loss or 0
            exit_time = (s.outcome or {}).get("exit_time") or "16:00"
            open_pos.append((exit_time, s.cost or 0))
            out.append(Decision(s, True, True, "taken"))
    return out
