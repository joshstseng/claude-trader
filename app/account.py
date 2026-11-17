"""The simulated $5k account for one trading day (Step 1b.3).

Alpaca's paper account has far more money than the ORB bot is sized for, so the app keeps its own
account and feeds it to the skill's risk check (check.py), which then enforces, on REAL entries:

    trades       at most max_trades_per_day entries a day          (state/broker.json)
    daily loss   max losses at the stops of today's entries <= limit (state/broker.json)
    cash         open positions + a new one must fit the account minus the cash buffer, no margin
                                                                      (state/portfolio.json)

Same rules as the backtest's selection (cash limit ON): open positions use their cost; a closed
position frees its cash; the day's P&L isn't reinvested. The account starts fresh each morning
(decided 2026-11-17); every execution is still kept (this file per day, and the trade log).

Files, per day, in runs/<date>/state/ (shared by every signal that day):
    account.json     this module's record: positions, entries, exits, P&L
    broker.json      what check.py reads as "placed today"
    portfolio.json   what check.py reads as the account
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
_lock = threading.Lock()


@dataclass
class Position:
    symbol: str
    signal_id: int | None
    qty: int
    entry_price: float
    cost: float
    max_loss: float
    opened_at: str
    status: str = "open"            # open / closed
    exit_price: float | None = None
    closed_at: str | None = None
    pnl: float | None = None


class DayAccount:
    def __init__(self, state_dir: Path, day: str, starting_cash: float):
        self.dir, self.day = Path(state_dir), day
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "account.json"
        if self.file.exists():
            doc = json.loads(self.file.read_text())
            self.starting_cash = doc["starting_cash"]
            self.positions = [Position(**p) for p in doc["positions"]]
            self.records = doc["records"]
        else:
            self.starting_cash, self.positions, self.records = float(starting_cash), [], []
            self._save()

    @classmethod
    def for_day(cls, runs_root: Path, day: str, rules: dict) -> "DayAccount":
        return cls(Path(runs_root) / day / "state", day, float(rules.get("budget") or 0))

    # ------------------------------------------------------------- the numbers

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "open"]

    @property
    def cash(self) -> float:
        """Starting cash minus what open positions cost (the backtest's cash rule)."""
        return round(self.starting_cash - sum(p.cost for p in self.open_positions), 2)

    @property
    def realized_pnl(self) -> float:
        return round(sum(p.pnl or 0 for p in self.positions if p.status == "closed"), 2)

    @property
    def entries_today(self) -> int:
        return sum(1 for r in self.records if r["kind"] == "entry" and r["status"] == "placed")

    # ---------------------------------------------------------------- changes

    def record_entry(self, symbol: str, qty: int, price: float, max_loss: float, *,
                     signal_id: int | None = None, at: datetime | None = None) -> None:
        """An entry order was placed (counts toward trades and daily loss from this moment)."""
        with _lock:
            when = (at or datetime.now(NY)).isoformat(timespec="seconds")
            self.records.append({"date": self.day, "at": when, "status": "placed", "kind": "entry",
                                 "symbol": symbol.upper(), "side": "buy", "qty": qty, "price": price,
                                 "max_loss": round(max_loss, 2), "signal_id": signal_id})
            self.positions.append(Position(symbol.upper(), signal_id, qty, price, round(qty * price, 2),
                                           round(max_loss, 2), when))
            self._save()

    def cancel_entry(self, symbol: str) -> None:
        """An entry that never filled (e.g. the limit wasn't reached): it no longer counts."""
        with _lock:
            for r in reversed(self.records):
                if r["symbol"] == symbol.upper() and r["kind"] == "entry" and r["status"] == "placed":
                    r["status"] = "cancelled"
                    break
            for p in self.open_positions:
                if p.symbol == symbol.upper():
                    self.positions.remove(p)
                    break
            self._save()

    def record_exit(self, symbol: str, price: float, *, at: datetime | None = None) -> Position:
        """A position closed (stop, target or 3:55 flatten): frees its cash, books its P&L."""
        with _lock:
            p = next((x for x in self.open_positions if x.symbol == symbol.upper()), None)
            if p is None:
                raise ValueError(f"no open position in {symbol}")
            when = (at or datetime.now(NY)).isoformat(timespec="seconds")
            p.status, p.exit_price, p.closed_at = "closed", price, when
            p.pnl = round((price - p.entry_price) * p.qty, 2)
            self.records.append({"date": self.day, "at": when, "status": "filled", "kind": "exit",
                                 "symbol": p.symbol, "side": "sell", "qty": p.qty, "price": price, "pnl": p.pnl})
            self._save()
            return p

    # ------------------------------------------------------------------ files

    def _save(self) -> None:
        doc = {"date": self.day, "starting_cash": self.starting_cash,
               "positions": [p.__dict__ for p in self.positions], "records": self.records}
        _write(self.file, doc)
        _write(self.dir / "broker.json", {"orders": self.records})          # check.py: placed today
        _write(self.dir / "portfolio.json", {                               # check.py: the account
            "cash": self.cash,
            "positions": [{"ticker": p.symbol, "shares": p.qty, "lots": [{"shares": p.qty, "cost": p.cost}]}
                          for p in self.open_positions]})

    @property
    def broker_file(self) -> Path:
        return self.dir / "broker.json"

    @property
    def portfolio_file(self) -> Path:
        return self.dir / "portfolio.json"


def _write(path: Path, doc) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(path)
