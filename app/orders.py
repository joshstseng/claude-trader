"""Approve → order (Step 1b.4). What happens when you tap [Approve] on a live alert:

  1. stale check   the alert is under `stale_minutes` old, and the latest price hasn't run more than
                   `stale_drift_r` x the risk past the entry, or fallen to the stop
  2. size again    at the LIMIT price (entry + the lesser of `limit_buffer_r` x risk and
                   `limit_buffer_pct`% of the entry), with the skill's size.size_trade, so the max
                   loss still fits after the buffer
  3. risk again    the skill's check.py with today's real account (trades, daily loss, cash)
  4. one order     a bracket on the Alpaca PAPER account: limit entry + stop + target; the client
                   order id orb-<date>-<signal> makes a retry or a double tap harmless
  5. bookkeeping   counted in today's account (from the moment it's placed), saved in the trade log

After `fill_timeout_seconds`, `check_entry` cancels an entry that hasn't filled and un-counts it.
Replay alerts and orders.enabled = false only record your choice.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import paths, pipeline, skill, tradelog
from app.account import DayAccount

log = logging.getLogger(__name__)
LIVE_ORDER_STATES = ("new", "accepted", "pending_new", "accepted_for_bidding", "held")


@dataclass
class Outcome:
    placed: bool
    text: str                     # the full line (for #trades / logs)
    client_id: str | None = None
    final: bool = True            # no more taps make sense (placed, refused for good)
    line: str | None = None       # what the alert in #setups becomes (None = leave it as is)
    state: str = "active"         # active = keep the card · live = one normal line · done = collapse


def _money(x: float) -> str:
    return f"${x:,.2f}"


class OrderDesk:
    def __init__(self, trade_log: tradelog.TradeLog, broker, strategy_settings: dict, rules: dict, *,
                 runs_root: Path = paths.RUNS_DIR, now: Callable[[], datetime] | None = None):
        self.log, self.broker, self.s, self.rules = trade_log, broker, strategy_settings, rules
        self.o = strategy_settings.get("orders", {})
        self.runs_root = runs_root
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()   # one approval at a time: two quick taps can't race
        self.pause_source = None        # e.g. the app's /pause and /flatten setting

    def approve(self, signal_id: int, user_id=None, *, source: str = "live") -> Outcome:
        with self._lock:
            return self._approve(signal_id, user_id, source=source)

    def check_entry(self, client_id: str) -> Outcome:
        with self._lock:
            return self._check_entry(client_id)

    def limit_price(self, entry: float, risk: float) -> float:
        buf = min(self.o.get("limit_buffer_r", 0.1) * risk, entry * self.o.get("limit_buffer_pct", 0.1) / 100)
        return round(entry + max(buf, 0.01), 2)

    def _approve(self, signal_id: int, user_id=None, *, source: str = "live") -> Outcome:
        sig = self.log.signal(signal_id)
        if source != "live":                             # replay / test alerts never order
            if sig is not None:
                self.log.record_response(signal_id, "took", user_id=user_id)
            return Outcome(False, "📝 Test/replay alert: approval noted, **no order is placed**. On a live "
                                  "alert this would run the stale check, the risk check and send the bracket order.",
                           line="📝 Approved (test alert: no order placed)", state="done")
        if sig is None:
            return Outcome(False, "⛔ I can't find that signal in the log.")
        if self.pause_source and self.pause_source():
            return Outcome(False, "⏸️ **Not placed**: the bot is paused (`/resume` to allow approvals).", final=False)
        if self.log.order_for_signal(signal_id) is not None:
            return Outcome(False, "Already placed: one order per alert.")
        if not self.o.get("enabled", False):
            self.log.record_response(signal_id, "took", user_id=user_id)
            return Outcome(False, "📝 Recorded. Ordering is switched off (`orders.enabled`), so nothing was placed.",
                           line="📝 Approved (ordering is off: nothing placed)", state="done")
        if sig["status"] != "pass":
            return Outcome(False, f"⛔ Not tradable: {sig['status']} ({sig['reason'] or 'no reason'}).",
                           line=f"⛔ Not tradable ({sig['status']})", state="done")

        sym, entry, stop, target = sig["symbol"], sig["entry"], sig["stop"], sig["target"]
        risk = entry - stop

        # 1. stale check
        alert_at = self.log.alert_at(signal_id)
        if alert_at:
            age = (self.now() - datetime.fromisoformat(alert_at)).total_seconds() / 60
            if age > self.o.get("stale_minutes", 5):
                return self._refuse(signal_id, f"stale: the alert is {age:.0f} minutes old "
                                               f"(limit {self.o.get('stale_minutes', 5)})")
        price = self.broker.last_price(sym)
        if price is None:
            return self._refuse(signal_id, "no fresh price to check against", final=False)
        if price > entry + self.o.get("stale_drift_r", 0.25) * risk:
            return self._refuse(signal_id, f"the price ran: {_money(price)} is more than "
                                           f"{self.o.get('stale_drift_r', 0.25)}R above the {_money(entry)} entry")
        if price <= stop:
            return self._refuse(signal_id, f"the price {_money(price)} is already at or below the stop {_money(stop)}")

        # 2. size again at the limit price (the skill's sizing)
        folder = Path(sig["folder"]) if sig["folder"] else None
        if folder is None or not (folder / "trader" / "plan.json").exists():
            return self._refuse(signal_id, "the signal's plan file is missing")
        plan = json.loads((folder / "trader" / "plan.json").read_text())
        limit = self.limit_price(entry, risk)
        size_mod = skill.module("size")
        sizing = size_mod.size_trade(plan, self.rules, limit=limit)
        if sizing["refusal"]:
            return self._refuse(signal_id, f"sizing at the {_money(limit)} limit: {sizing['refusal']}")
        order = size_mod.bracket_order(sizing)
        size_mod.write_orders(str(folder / "trader" / "orders.json"), [order], self.rules,
                              source="approve", now_utc=self.now().replace(tzinfo=None))

        # 3. the skill's risk check, again, on today's real account
        acct = DayAccount.for_day(self.runs_root, sig["date"], self.rules)
        verdict, reasons = pipeline.risk_check(
            folder, acct, sig["date"], now=self.now().astimezone(pipeline.NY).strftime("%Y-%m-%d %H:%M"))
        if verdict != "PASS":
            return self._refuse(signal_id, "risk check: " + ("; ".join(reasons) or verdict or "no verdict"))

        # 4. one order
        qty = int(sizing["qty"])
        client_id = f"orb-{sig['date']}-{signal_id}"
        try:
            info = self.broker.bracket_buy(sym, qty, limit, stop, target, client_id)
        except Exception as e:  # noqa: BLE001 - Alpaca refused it: say why, place nothing
            existing = self.broker.order(client_id)            # e.g. a double tap raced us: it exists
            if existing is None:
                log.warning("order for %s refused by Alpaca: %s", sym, e)
                self.log.add_order(signal_id, client_id, sym, qty, limit, stop, target, status="rejected")
                self.log.update_order(client_id, note=str(e)[:300])
                return Outcome(False, f"⛔ Alpaca refused the order: {str(e)[:150]}",
                               line=f"⛔ Alpaca refused the order ({str(e)[:80]})", state="done")
            info = existing

        # 5. bookkeeping
        acct.record_entry(sym, qty, limit, sizing["max_loss"], signal_id=signal_id)
        self.log.add_order(signal_id, client_id, sym, qty, limit, stop, target, broker_order_id=info.broker_id)
        self.log.update_order(client_id, stop_order_id=info.stop_id, target_order_id=info.target_id)
        self.log.record_response(signal_id, "took", user_id=user_id)
        log.info("order placed: buy %d %s limit %.2f stop %.2f target %.2f (%s)", qty, sym, limit, stop,
                 target, client_id)
        line = (f"⏳ **{sym}** · order sent: buy {qty} at limit {_money(limit)} · stop {_money(stop)} · "
                f"target {_money(target)}")
        return Outcome(True, f"⏳ **Order sent** (paper): buy {qty} {sym} limit {_money(limit)} · "
                             f"stop {_money(stop)} · target {_money(target)} · max loss {_money(sizing['max_loss'])}",
                       client_id, line=line, state="live")

    def _check_entry(self, client_id: str) -> Outcome:
        """After the fill timeout: filled → keep; still waiting → cancel and un-count it."""
        row = self.log.db.execute("SELECT * FROM orders WHERE client_order_id = ?", (client_id,)).fetchone()
        if row is None:
            return Outcome(False, "⛔ unknown order")
        info = self.broker.order(client_id)
        if info is None:
            return Outcome(False, "⚠️ Alpaca doesn't know this order")
        if info.status == "filled":
            self.log.update_order(client_id, status="filled", filled_qty=info.filled_qty,
                                  filled_price=info.filled_price, filled_at=self.now().isoformat(timespec="seconds"))
            if info.filled_price and info.filled_qty:
                sig = self.log.signal(row["signal_id"])
                DayAccount.for_day(self.runs_root, sig["date"], self.rules).update_fill(
                    row["symbol"], info.filled_qty, info.filled_price)
            slip = (info.filled_price or 0) - (row["limit_price"] or 0)
            in_trade = (f"🟢 **{row['symbol']}** · in trade: {info.filled_qty} @ {_money(info.filled_price)} · "
                        f"stop {_money(row['stop'])} · target {_money(row['target'])}")
            return Outcome(True, f"✅ **Filled** {info.filled_qty} {row['symbol']} at {_money(info.filled_price)} "
                                 f"({'−' if slip < 0 else '+'}{_money(abs(slip))} vs the limit). "
                                 f"Stop and target are live at Alpaca.", client_id, line=in_trade, state="live")
        if info.status == "partially_filled":
            self.log.update_order(client_id, status="partially_filled", filled_qty=info.filled_qty,
                                  filled_price=info.filled_price)
            return Outcome(True, f"◐ Partly filled: {info.filled_qty} of {row['qty']} {row['symbol']} at "
                                 f"{_money(info.filled_price)}. Tracking continues.", client_id,
                           line=(f"◐ **{row['symbol']}** · partly filled {info.filled_qty}/{row['qty']} @ "
                                 f"{_money(info.filled_price)} · stop {_money(row['stop'])} · target {_money(row['target'])}"),
                           state="live")
        if info.status in LIVE_ORDER_STATES:
            try:
                self.broker.cancel(info.broker_id)
            except Exception as e:  # noqa: BLE001
                log.error("couldn't cancel unfilled %s: %s", client_id, e)
                return Outcome(False, f"⚠️ Not filled, and cancelling failed: {str(e)[:120]}", client_id)
            sig = self.log.signal(row["signal_id"])
            DayAccount.for_day(self.runs_root, sig["date"], self.rules).cancel_entry(row["symbol"])
            self.log.update_order(client_id, status="cancelled", note="not filled within the timeout")
            return Outcome(False, f"⌛ **Not filled** within {self.o.get('fill_timeout_seconds', 120)}s at the "
                                  f"{_money(row['limit_price'])} limit: cancelled, nothing bought.", client_id,
                           line=f"⌛ {row['symbol']} · limit {_money(row['limit_price'])} never filled, nothing bought",
                           state="done")
        self.log.update_order(client_id, status=info.status)
        if info.status in ("canceled", "cancelled", "expired", "rejected"):
            sig = self.log.signal(row["signal_id"])
            DayAccount.for_day(self.runs_root, sig["date"], self.rules).cancel_entry(row["symbol"])
        return Outcome(False, f"Order is {info.status}.", client_id)

    def _refuse(self, signal_id: int, why: str, final: bool = True) -> Outcome:
        log.info("approval refused for signal %s: %s", signal_id, why)
        return Outcome(False, f"⛔ **Not placed**: {why}.", final=final,
                       line=f"⛔ Not placed ({why})" if final else None, state="done" if final else "active")
