"""Out by the close (Step 1b.6). Nothing is ever held overnight.

    3:55 PM (12:55 on an early close)  flatten(): cancel every open order (stops, targets, unfilled
                                       entries) and sell every position at market, then book each
                                       exit in today's account and the trade log
    3:58 PM                            backup: anything still open is flattened again, and you're
                                       @mentioned (via an ERROR log line) if something is left
    any time                           /flatten in Discord: the same, now, and the bot pauses

Alpaca won't do this for us: at the close it cancels a bracket's stop and target but leaves the
shares. The paper account is the bot's alone, so "everything in the account" is what gets closed.

Positions that already exited (stop or target hit earlier) are booked from their bracket's legs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import paths, tradelog
from app.account import DayAccount

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
ICON = {"target": "✅", "stop": "❌", "flat": "➖", "flatten": "🛑"}


@dataclass
class FlattenReport:
    phase: str                                                 # flat / backup / kill switch
    exits: list[tuple] = field(default_factory=list)           # (symbol, qty, reason, price, pnl)
    cancelled_entries: list[str] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def anything(self) -> bool:
        return bool(self.exits or self.cancelled_entries or self.still_open or self.problems)

    def text(self) -> str:
        head = {"flat": "🏁 **[ORB] 3:55 PM: out for the day**", "backup": "🛟 **[ORB] Backup check**",
                "kill switch": "🛑 **[ORB] Flattened by /flatten**"}.get(self.phase, f"**[ORB] {self.phase}**")
        lines = [head]
        for sym, qty, reason, price, pnl in self.exits:
            p = f"{'+' if (pnl or 0) >= 0 else '−'}${abs(pnl or 0):,.2f}" if pnl is not None else "P&L unknown"
            px = f"${price:,.2f}" if price is not None else "price unknown"
            lines.append(f"{ICON.get(reason, '•')} {sym}: {qty} sh, {reason} at {px} ({p})")
        if self.cancelled_entries:
            lines.append("⌛ Unfilled entries cancelled: " + ", ".join(self.cancelled_entries))
        if self.still_open:
            lines.append("⚠️ **Still open:** " + ", ".join(self.still_open))
        lines += [f"⚠️ {p}" for p in self.problems]
        total = sum(e[4] or 0 for e in self.exits)
        if self.exits:
            lines.append(f"Today's closed P&L from these: {'+' if total >= 0 else '−'}${abs(total):,.2f}")
        return "\n".join(lines)


class Flattener:
    def __init__(self, broker, trade_log: tradelog.TradeLog, rules: dict, *, runs_root: Path = paths.RUNS_DIR,
                 fill_wait_s: float = 10.0, now=lambda: datetime.now(NY)):
        self.broker, self.log, self.rules, self.runs_root = broker, trade_log, rules, runs_root
        self.fill_wait_s, self.now = fill_wait_s, now

    def flatten(self, day: str, phase: str = "flat") -> FlattenReport:
        rep = FlattenReport(phase)
        acct = DayAccount.for_day(self.runs_root, day, self.rules)
        try:
            closing = dict(self.broker.close_all())               # {symbol: close order id}
        except Exception as e:  # noqa: BLE001
            log.error("[ORB] flatten (%s): closing positions failed: %s", phase, e)
            rep.problems.append(f"closing positions failed: {str(e)[:150]}")
            closing = {}
        fills = self._wait_for_fills(closing)

        for pos in list(acct.open_positions):
            order = self.log.db.execute("SELECT * FROM orders WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
                                        (pos.signal_id,)).fetchone() if pos.signal_id else None
            reason, price, when = None, None, None
            if pos.symbol in closing:                              # we just sold it
                reason, price = "flat" if phase != "kill switch" else "flatten", fills.get(pos.symbol)
            elif order is not None:
                done = self._exit_from_legs(order["client_order_id"])
                if done:                                           # stop or target hit earlier today
                    reason, price, when = done
                elif order["status"] in ("submitted", "accepted", "new"):
                    acct.cancel_entry(pos.symbol)                  # entry never filled: close_all cancelled it
                    self.log.update_order(order["client_order_id"], status="cancelled",
                                          note=f"cancelled at the {phase}")
                    rep.cancelled_entries.append(pos.symbol)
                    continue
            if reason is None:
                rep.problems.append(f"{pos.symbol}: can't tell how it closed; check Alpaca")
                continue
            if price is None:
                rep.problems.append(f"{pos.symbol}: closed, but the fill price isn't in yet")
                price = pos.entry_price                            # booked flat for now; 1b.5 corrects it
            closed = acct.record_exit(pos.symbol, price, reason=reason)
            if order is not None:
                self.log.update_order(order["client_order_id"], status="closed", exit_reason=reason,
                                      exit_price=price, exited_at=when or self.now().isoformat(timespec="seconds"),
                                      pnl_usd=closed.pnl)
            rep.exits.append((pos.symbol, pos.qty, reason, price, closed.pnl))

        # anything Alpaca still holds (or still has orders for) after all that
        try:
            rep.still_open = sorted({p["symbol"] for p in self.broker.positions()} |
                                    {o.client_id for o in self.broker.open_orders()})
        except Exception as e:  # noqa: BLE001
            rep.problems.append(f"couldn't re-check Alpaca: {str(e)[:120]}")
        if rep.still_open:
            log.error("[ORB] %s: still open after flattening: %s", phase, ", ".join(rep.still_open))
        return rep

    def _wait_for_fills(self, closing: dict) -> dict:
        fills, deadline = {}, time.monotonic() + self.fill_wait_s
        pending = {s: oid for s, oid in closing.items() if oid}
        while pending and time.monotonic() < deadline:
            for sym, oid in list(pending.items()):
                try:
                    status, price = self.broker.fill_of(oid)
                except Exception:  # noqa: BLE001
                    continue
                if status == "filled" and price:
                    fills[sym] = price
                    del pending[sym]
            if pending:
                time.sleep(1)
        return fills

    def _exit_from_legs(self, client_id: str):
        try:
            return self.broker.exit_fill(client_id)
        except Exception:  # noqa: BLE001
            return None
