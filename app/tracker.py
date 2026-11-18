"""Live trade tracking (Step 1b.5): Alpaca's stream of order events -> the books and #trades.

    entry filled          -> order marked filled, entry slippage (fill vs the plan's entry) recorded
    entry partly filled   -> noted
    entry cancelled       -> un-counted from today's account (nothing was bought)
    stop or target filled -> exit booked in today's account, P&L and R, exit slippage recorded

Events are matched to our orders by id: the entry by its client id (orb-<date>-<signal>), the exits by
the bracket's stop/target order ids saved when the order was placed. Anything else (e.g. the 3:55
flatten's own sells, which flatten.py books) is ignored. Each event is handled once.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app import paths, tradelog
from app.account import DayAccount

log = logging.getLogger(__name__)
FINAL = ("filled", "closed", "cancelled", "rejected", "expired")


def _v(x):
    return getattr(x, "value", x)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _signed(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


@dataclass
class Update:
    signal_id: int
    text: str                  # for #trades
    line: str | None = None    # what the alert in #setups becomes
    state: str = "live"        # live = one normal line (in a trade) · done = collapsed (finished)


class TradeTracker:
    def __init__(self, trade_log: tradelog.TradeLog, rules: dict, *, runs_root: Path = paths.RUNS_DIR):
        self.log, self.rules, self.runs_root = trade_log, rules, runs_root
        self._lock = threading.Lock()

    def handle(self, event, order) -> Update | None:
        """One Alpaca trade update. `order` has id, client_order_id, symbol, filled_qty,
        filled_avg_price, filled_at."""
        with self._lock:
            event = str(_v(event))
            found = (self.log.order_by_any_id(str(order.client_order_id or ""))
                     or self.log.order_by_any_id(str(order.id)))
            if found is None:
                return None                      # not one of ours (e.g. the flatten's own sells)
            row, part = found
            sig = self.log.signal(row["signal_id"])
            acct = DayAccount.for_day(self.runs_root, sig["date"], self.rules)
            if part == "entry":
                return self._entry(event, order, row, sig, acct)
            return self._exit(event, order, row, sig, acct, part)

    # ------------------------------------------------------------------ entry

    def _entry(self, event, order, row, sig, acct) -> Update | None:
        cid, sym = row["client_order_id"], row["symbol"]
        qty = int(float(order.filled_qty or 0))
        price = float(order.filled_avg_price) if order.filled_avg_price else None
        if event == "fill":
            if row["status"] in ("filled", "closed"):
                return None                      # already handled (e.g. by the 2-minute check)
            slip = round(price - sig["entry"], 4) if price is not None else None
            self.log.update_order(cid, status="filled", filled_qty=qty, filled_price=price,
                                  filled_at=str(order.filled_at or ""), entry_slippage=slip)
            if price is not None and qty:
                acct.update_fill(sym, qty, price)        # book the real fill, not the limit
            return Update(row["signal_id"],
                          f"🟢 **Bought {sym}**: {qty} at {_money(price)} · plan {_money(sig['entry'])} "
                          f"({_signed(slip or 0)} a share slippage) · stop {_money(row['stop'])} · "
                          f"target {_money(row['target'])}",
                          line=(f"🟢 **{sym}** · in trade: {qty} @ {_money(price)} · stop {_money(row['stop'])}"
                                f" · target {_money(row['target'])}"), state="live")
        if event == "partial_fill":
            self.log.update_order(cid, status="partially_filled", filled_qty=qty, filled_price=price)
            return Update(row["signal_id"], f"◐ **{sym}** partly filled: {qty} of {row['qty']} at {_money(price)}",
                          line=(f"◐ **{sym}** · partly filled {qty}/{row['qty']} @ {_money(price)} · "
                                f"stop {_money(row['stop'])} · target {_money(row['target'])}"), state="live")
        if event in ("canceled", "expired", "rejected"):
            if row["status"] in FINAL:
                return None
            if qty == 0:
                acct.cancel_entry(sym)
            self.log.update_order(cid, status="cancelled" if event != "rejected" else "rejected",
                                  note=f"entry {event}")
            if qty == 0:
                return Update(row["signal_id"], f"⌛ **{sym}** entry {event}: nothing bought",
                              line=f"⌛ {sym} · entry {event}, nothing bought", state="done")
        return None

    # ------------------------------------------------------------------ exits

    def _exit(self, event, order, row, sig, acct, part) -> Update | None:
        if event != "fill":
            return None                          # the other leg cancelled by Alpaca: nothing to do
        cid, sym = row["client_order_id"], row["symbol"]
        if row["status"] == "closed":
            return None                          # already booked (e.g. by the flatten)
        price = float(order.filled_avg_price)
        if not any(p.symbol == sym for p in acct.open_positions):
            return None
        closed = acct.record_exit(sym, price, reason=part)
        entry_px = row["filled_price"] or row["limit_price"]
        risk = sig["entry"] - sig["stop"]
        r = (price - entry_px) / risk if risk else 0.0
        planned = row["stop"] if part == "stop" else row["target"]
        self.log.update_order(cid, status="closed", exit_reason=part, exit_price=price,
                              exited_at=str(order.filled_at or ""), pnl_usd=closed.pnl,
                              exit_slippage=round(price - planned, 4))
        head = "✅ **Target hit**" if part == "target" else "❌ **Stopped out**"
        word = "target hit" if part == "target" else "stopped out"
        icon = "✅" if part == "target" else "❌"
        line = (f"{icon} {sym} · {word} at {_money(price)} · {_signed(closed.pnl)} · "
                f"{r:+.2f}R").replace("-", "−")
        return Update(row["signal_id"],
                      f"{head} {sym}: sold {closed.qty} at {_money(price)} ({part} {_money(planned)}) · "
                      f"**{_signed(closed.pnl)}** · {r:+.2f}R · today's closed P&L {_signed(acct.realized_pnl)}".replace("-", "−"),
                      line=line, state="done")
