"""Restart safety (Step 1b.7): on every start, line up the books with what Alpaca actually holds.

Stops and targets live at Alpaca, so a restart never leaves a trade unprotected. What a restart CAN
lose is our side of the story: fills that happened while the app was down, the 2-minute fill check
for a fresh entry, and (worst case) the 3:55 flatten if the app was down right then. So on start:

  entry filled while down          -> booked with the real fill
  stop / target hit while down     -> exit booked from the bracket's legs, posted to #trades
  entry still waiting              -> cancelled if its fill timeout has passed; otherwise its fill
                                      check is rescheduled
  entry cancelled while down       -> un-counted
  position held while the market   -> ERROR (pings you) and a sell is queued for the next open
  is closed (missed flatten)
  position we don't know about     -> ERROR (pings you)

Between 3:55 and the close, the scheduler's flatten runs right away on its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app import paths, tradelog
from app.account import DayAccount
from app.market import Session
from app.strategies import tag as _tag

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
WAITING = ("new", "accepted", "pending_new", "accepted_for_bidding", "held")


@dataclass
class ReconcileReport:
    notes: list[str] = field(default_factory=list)            # for #system
    trades: list[str] = field(default_factory=list)           # for #trades
    problems: list[str] = field(default_factory=list)         # ping-worthy
    recheck: list[tuple[str, float]] = field(default_factory=list)   # (client id, seconds until its fill check)
    alert_updates: list[tuple] = field(default_factory=list)          # (signal id, line, "live"|"done")

    @property
    def anything(self) -> bool:
        return bool(self.notes or self.trades or self.problems)

    def text(self) -> str:
        lines = ["🔄 **[" + _tag() + "] Restart check** (books vs Alpaca)"]
        lines += [f"• {n}" for n in self.notes] + [f"• {t}" for t in self.trades]
        lines += [f"⚠️ {p}" for p in self.problems]
        return "\n".join(lines)


class Reconciler:
    def __init__(self, broker, trade_log: tradelog.TradeLog, rules: dict, fill_timeout_s: int = 120, *,
                 runs_root: Path = paths.RUNS_DIR, now=lambda: datetime.now(NY)):
        self.broker, self.log, self.rules, self.timeout = broker, trade_log, rules, fill_timeout_s
        self.runs_root, self.now = runs_root, now

    def reconcile(self, session: Session | None) -> ReconcileReport:
        rep = ReconcileReport()
        now = self.now()
        day = now.date().isoformat()
        acct = DayAccount.for_day(self.runs_root, day, self.rules)

        # 1. today's orders: what happened while we were away?
        rows = self.log.db.execute(
            "SELECT o.* FROM orders o JOIN signals s ON s.id = o.signal_id WHERE s.date = ? AND s.source = 'live'"
            " AND o.status IN ('submitted', 'partially_filled', 'filled')", (day,)).fetchall()
        for row in rows:
            cid, sym = row["client_order_id"], row["symbol"]
            info = self.broker.order(cid)
            if info is None:
                rep.problems.append(f"{sym}: Alpaca doesn't know order {cid}")
                continue
            if info.status == "filled" and row["status"] != "filled":
                self.log.update_order(cid, status="filled", filled_qty=info.filled_qty, filled_price=info.filled_price)
                if info.filled_price and info.filled_qty:
                    acct.update_fill(sym, info.filled_qty, info.filled_price)
                rep.notes.append(f"{sym}: entry filled while I was away ({info.filled_qty} at ${info.filled_price:,.2f})")
                rep.alert_updates.append((row["signal_id"], f"🟢 **[{_tag()}] {sym}** · in trade: {info.filled_qty} @ "
                                          f"${info.filled_price:,.2f} · stop ${row['stop']:,.2f} · target "
                                          f"${row['target']:,.2f}", "live"))
            elif info.status in WAITING:
                age = (now - datetime.fromisoformat(row["submitted_at"])).total_seconds()
                if age >= self.timeout:
                    self.broker.cancel(info.broker_id)
                    acct.cancel_entry(sym)
                    self.log.update_order(cid, status="cancelled", note="not filled in time (found on restart)")
                    rep.notes.append(f"{sym}: entry never filled, cancelled")
                    rep.alert_updates.append((row["signal_id"], f"⌛ [{_tag()}] {sym} · limit never filled, nothing bought",
                                              "done"))
                else:
                    rep.recheck.append((cid, self.timeout - age))
            elif info.status in ("canceled", "cancelled", "expired", "rejected") and info.filled_qty == 0:
                acct.cancel_entry(sym)
                self.log.update_order(cid, status="cancelled", note=f"entry {info.status} while I was away")
                rep.notes.append(f"{sym}: entry {info.status} while I was away, nothing bought")
                rep.alert_updates.append((row["signal_id"], f"⌛ [{_tag()}] {sym} · entry {info.status}, nothing bought",
                                          "done"))

        # 2. positions: ours vs Alpaca's
        held = {p["symbol"]: p["qty"] for p in self.broker.positions()}
        for pos in list(acct.open_positions):
            if pos.symbol in held:
                continue                                           # still open, protected at Alpaca
            row = self.log.order_for_signal(pos.signal_id) if pos.signal_id else None
            if row is None or row["status"] in ("submitted", "partially_filled"):
                continue                                           # entry not filled yet: handled above
            done = None
            try:
                done = self.broker.exit_fill(row["client_order_id"])
            except Exception:  # noqa: BLE001
                pass
            if done is None:
                rep.problems.append(f"{pos.symbol}: in my books but not at Alpaca, and I can't see how it closed")
                continue
            reason, price, when = done
            closed = acct.record_exit(pos.symbol, price, reason=reason)
            self.log.update_order(row["client_order_id"], status="closed", exit_reason=reason, exit_price=price,
                                  exited_at=when, pnl_usd=closed.pnl)
            icon = "✅ Target hit" if reason == "target" else "❌ Stopped out"
            rep.trades.append(f"{icon} {pos.symbol} while I was away: {closed.qty} at ${price:,.2f} "
                              f"({'+' if closed.pnl >= 0 else '−'}${abs(closed.pnl):,.2f})")
            rep.alert_updates.append((pos.signal_id, f"{'✅' if reason == 'target' else '❌'} [{_tag()}] {pos.symbol} · "
                                      f"{'target hit' if reason == 'target' else 'stopped out'} at ${price:,.2f} · "
                                      f"{'+' if closed.pnl >= 0 else '−'}${abs(closed.pnl):,.2f}", "done"))
        ours = {p.symbol for p in acct.open_positions}
        for sym in sorted(set(held) - ours):
            rep.problems.append(f"{sym}: Alpaca holds {held[sym]} shares that aren't in today's books")

        # 3. anything held while the market is closed means a flatten was missed
        open_now = session is not None and session.at(session.open) <= now < session.at(session.close)
        if held and not open_now:
            try:
                self.broker.close_all()
                rep.problems.append(f"open while the market is closed: {', '.join(sorted(held))}. "
                                    f"Sells are queued for the next open")
            except Exception as e:  # noqa: BLE001
                rep.problems.append(f"open while the market is closed: {', '.join(sorted(held))}, and queuing "
                                    f"sells failed ({str(e)[:100]}). Close them in Alpaca")
        elif held:
            rep.notes.append(f"open and protected at Alpaca: {', '.join(f'{s} {q}' for s, q in sorted(held.items()))}")

        for p in rep.problems:
            log.error("restart check: %s", p)                # pings you in #system
        return rep
