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
    alert_updates: list[tuple] = field(default_factory=list)  # (signal id, line, "done") for #setups

    @property
    def anything(self) -> bool:
        return bool(self.exits or self.cancelled_entries or self.still_open or self.problems)

    def text(self) -> str:
        head = {"flat": "🏁 **3:55 PM: out for the day**", "backup": "🛟 **Backup check**",
                "kill switch": "🛑 **Flattened by /flatten**"}.get(self.phase, f"**{self.phase}**")
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
                 fill_wait_s: float = 10.0, recheck_s: float = 10.0, now=lambda: datetime.now(NY)):
        self.broker, self.log, self.rules, self.runs_root = broker, trade_log, rules, runs_root
        self.fill_wait_s, self.now = fill_wait_s, now
        self.recheck_s = recheck_s

    def flatten(self, day: str, phase: str = "flat") -> FlattenReport:
        rep = FlattenReport(phase)
        acct = DayAccount.for_day(self.runs_root, day, self.rules)
        try:
            closing = dict(self.broker.close_all())               # {symbol: close order id}
        except Exception as e:  # noqa: BLE001
            log.error("flatten (%s): closing positions failed: %s", phase, e)
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
                    rep.alert_updates.append((pos.signal_id, f"⌛ {pos.symbol} · entry cancelled at the "
                                                             f"{phase}, nothing bought", "done"))
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
            words = {"flat": "sold at the close", "flatten": "closed by /flatten", "stop": "stopped out",
                     "target": "target hit"}.get(reason, reason)
            pnl = closed.pnl or 0
            rep.alert_updates.append((pos.signal_id, f"{ICON.get(reason, '•')} {pos.symbol} · {words} at "
                                                     f"${price:,.2f} · {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f}", "done"))

        # anything Alpaca still holds (or still has orders for) after all that. Sells that are still
        # filling look "open" for a moment, so re-check for a few seconds before calling it a problem.
        deadline = time.monotonic() + self.recheck_s
        while True:
            try:
                rep.still_open = sorted({p["symbol"] for p in self.broker.positions()} |
                                        {o.client_id for o in self.broker.open_orders()})
            except Exception as e:  # noqa: BLE001
                rep.problems.append(f"couldn't re-check Alpaca: {str(e)[:120]}")
                break
            if not rep.still_open or time.monotonic() >= deadline:
                break
            time.sleep(1)
        if rep.still_open:
            log.error("%s: still open after flattening: %s", phase, ", ".join(rep.still_open))
        return rep

    def repair_exits(self, day: str) -> list[tuple]:
        """After the close: any exit booked at the close or by /flatten or Close now whose recorded
        price differs from the real sell fill at Alpaca gets corrected (order, account, P&L).
        Returns [(client id, symbol, old price, new price, new P&L)]."""
        fixed = []
        rows = self.log.db.execute(
            "SELECT o.* FROM orders o JOIN signals s ON s.id = o.signal_id WHERE s.date = ? AND o.status = 'closed'"
            " AND o.exit_reason IN ('flat', 'flatten', 'manual')", (day,)).fetchall()
        acct = DayAccount.for_day(self.runs_root, day, self.rules)
        for row in rows:
            try:
                fill = self.broker.last_sell_fill(row["symbol"], after=row["filled_at"])
            except Exception as e:  # noqa: BLE001
                log.warning("repair: couldn't look up %s's sell: %s", row["symbol"], e)
                continue
            if fill is None or row["exit_price"] is not None and abs(fill[0] - row["exit_price"]) < 0.005:
                continue
            price, when = fill
            fp = row["filled_price"] or row["limit_price"]
            qty = row["filled_qty"] or row["qty"]
            pnl = round((price - fp) * qty, 2)
            self.log.update_order(row["client_order_id"], exit_price=price, exited_at=when, pnl_usd=pnl)
            acct.correct_exit(row["symbol"], price)
            fixed.append((row["client_order_id"], row["symbol"], row["exit_price"], price, pnl))
            log.info("repair: %s exit %s -> %.2f (P&L %.2f)", row["symbol"], row["exit_price"], price, pnl)
        return fixed

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
