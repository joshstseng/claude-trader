"""Managing an open paper trade from its card in #live-trades (Step 1b.9).

    cancel        an entry that hasn't filled: cancelled, nothing bought, not counted
    close         sells now at market (the stop and target are cancelled first), booked as "manual"
    breakeven     the stop moves to your entry fill
    move_stop     the stop moves to your price: ONLY UPWARD (less risk), and below the current price
    move_target   the target moves to your price: above the current price

Changes are made on the bracket at Alpaca (the leg is modified in place; Alpaca gives it a new id,
saved so the fill tracker still recognises it). Every change is logged as a trade event.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import paths, tradelog
from app.account import DayAccount

log = logging.getLogger(__name__)
LIVE = ("submitted", "partially_filled", "filled")


def _m(x: float) -> str:
    return f"${x:,.2f}"


@dataclass
class Result:
    ok: bool
    message: str            # shown to you (privately) after the tap
    closed: bool = False    # the trade is over: its card moves to #closed-trades
    cancelled: bool = False  # an entry that never filled: its card is removed


class TradeManager:
    def __init__(self, broker, trade_log: tradelog.TradeLog, rules: dict, *, runs_root: Path = paths.RUNS_DIR,
                 fill_wait_s: float = 10.0):
        self.broker, self.log, self.rules, self.runs_root = broker, trade_log, rules, runs_root
        self.fill_wait_s = fill_wait_s
        self._lock = threading.Lock()

    # ------------------------------------------------------------------- helpers

    def _get(self, cid: str):
        row = self.log.order(cid)
        if row is None:
            return None, None, Result(False, "I can't find that trade.")
        if row["status"] not in LIVE:
            return None, None, Result(False, f"This trade is already {row['status']}.")
        return row, self.log.signal(row["signal_id"]), None

    def _acct(self, sig) -> DayAccount:
        return DayAccount.for_day(self.runs_root, sig["date"], self.rules)

    def _filled(self, row) -> bool:
        return row["status"] == "filled" and row["filled_price"] is not None

    # ------------------------------------------------------------------- actions

    def cancel(self, cid: str) -> Result:
        with self._lock:
            row, sig, err = self._get(cid)
            if err:
                return err
            if row["status"] != "submitted":
                return Result(False, "It has already (partly) filled. Use **Close now** instead.")
            info = self.broker.order(cid)
            if info is not None and info.status == "filled":
                return Result(False, "It just filled. Use **Close now** instead.")
            self.broker.cancel(row["broker_order_id"])
            self._acct(sig).cancel_entry(row["symbol"])
            self.log.update_order(cid, status="cancelled", note="cancelled by you")
            self.log.add_event(cid, "cancelled", note="entry cancelled by you")
            return Result(True, f"Cancelled: nothing bought in {row['symbol']}.", cancelled=True)

    def close(self, cid: str) -> Result:
        with self._lock:
            row, sig, err = self._get(cid)
            if err:
                return err
            if not self._filled(row):
                return Result(False, "The entry hasn't filled yet. Use **Cancel order** instead.")
            legs = [x for x in (row["stop_order_id"], row["target_order_id"]) if x]
            sell_id = self.broker.close_now(row["symbol"], legs)
            price = None
            deadline = time.monotonic() + self.fill_wait_s
            while time.monotonic() < deadline:
                status, price = self.broker.fill_of(sell_id)
                if status == "filled" and price:
                    break
                time.sleep(0.5)
            if not price:
                return Result(False, "The sell was sent but hasn't filled yet. The card updates when it does.")
            pos = self._acct(sig).record_exit(row["symbol"], price, reason="manual")
            self.log.update_order(cid, status="closed", exit_reason="manual", exit_price=price,
                                  exited_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                                  pnl_usd=pos.pnl, exit_slippage=None)
            self.log.add_event(cid, "closed_manually", new=price)
            return Result(True, f"Closed {row['symbol']}: sold {pos.qty} at {_m(price)} "
                                f"({'+' if pos.pnl >= 0 else '−'}{_m(abs(pos.pnl))}).", closed=True)

    def breakeven(self, cid: str) -> Result:
        with self._lock:
            row, sig, err = self._get(cid)
            if err:
                return err
            if not self._filled(row):
                return Result(False, "The entry hasn't filled yet.")
            return self._set_stop(row, round(row["filled_price"], 2), kind="breakeven")

    def move_stop(self, cid: str, new_stop: float) -> Result:
        with self._lock:
            row, sig, err = self._get(cid)
            if err:
                return err
            if not self._filled(row):
                return Result(False, "The entry hasn't filled yet.")
            return self._set_stop(row, round(float(new_stop), 2), kind="stop_moved")

    def move_target(self, cid: str, new_target: float) -> Result:
        with self._lock:
            row, sig, err = self._get(cid)
            if err:
                return err
            if not self._filled(row):
                return Result(False, "The entry hasn't filled yet.")
            new = round(float(new_target), 2)
            price = self.broker.price(row["symbol"])
            if price is not None and new <= price + 0.01:
                return Result(False, f"The target must be above the current price ({_m(price)}).")
            if new == row["target"]:
                return Result(False, f"The target is already {_m(new)}.")
            new_id = self.broker.replace_leg(row["target_order_id"], limit_price=new)
            self.log.update_order(row["client_order_id"], target=new, target_order_id=new_id)
            self.log.add_event(row["client_order_id"], "target_moved", old=row["target"], new=new)
            return Result(True, f"Target moved: {_m(row['target'])} → {_m(new)}.")

    def _set_stop(self, row, new: float, *, kind: str) -> Result:
        """Stops only move UP (less risk) and must stay below the current price."""
        old = row["stop"]
        if new <= old:
            what = "your entry" if kind == "breakeven" else _m(new)
            return Result(False, f"Stops only move up: {what} isn't above the current stop {_m(old)}.")
        price = self.broker.price(row["symbol"])
        if price is not None and new >= price - 0.01:
            return Result(False, f"The stop must be below the current price ({_m(price)}), or it would sell "
                                 f"right away. Use **Close now** for that.")
        new_id = self.broker.replace_leg(row["stop_order_id"], stop_price=new)
        self.log.update_order(row["client_order_id"], stop=new, stop_order_id=new_id)
        self.log.add_event(row["client_order_id"], kind, old=old, new=new)
        label = "Stop moved to break-even" if kind == "breakeven" else "Stop moved"
        return Result(True, f"{label}: {_m(old)} → {_m(new)}.")
