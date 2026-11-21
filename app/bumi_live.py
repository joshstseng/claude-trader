"""Bumi's multi-day routine (Step 4). Separate from Orbi's day-trading code; app/bumi_run.py runs it.

    after the close   decide: read final bars and VIX, save tomorrow's plan and orders. Never sends anything
    about 9:00 AM ET  send: market-on-open orders, paper mode only, once per plan
    after the open    confirm: check fills and report anything that doesn't match

BUMI_MODE=paper is the only value that can send orders. Anything else is shadow. The plan is saved to disk, so a
restart neither loses it nor sends it twice, and client order ids make a repeated send harmless at Alpaca too.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import paths
from app.research.data import D
from app.settings import _read_json
from app.strategies import bumi

NY = ZoneInfo("America/New_York")
AFTER_CLOSE_MIN = 30          # final bars: Alpaca's free plan can't read the last 15 minutes
SEND_AT = dtime(9, 0)
LAST_SEND = dtime(9, 27)
CONFIRM_AFTER = dtime(9, 35)
CASH_BUFFER = 0.005            # sizes buys slightly under target, so a gap up can't overspend the account
STATE_FILE = paths.bot_dir("bumi") / "data" / "bumi_state.json"


def mode() -> str:
    return "paper" if (os.environ.get("BUMI_MODE") or "").strip().lower() == "paper" else "shadow"


def load_settings() -> dict:
    return _read_json(paths.STRATEGY_CONFIG_DIR / "bumi.json")


@dataclass
class Order:
    sym: str
    side: str
    qty: int
    why: str
    client_id: str
    status: str = "planned"


class State:
    """Bumi's saved plans. Written atomically, so a crash can't leave half a file."""

    def __init__(self, path: Path = STATE_FILE):
        self.path = Path(path)
        self.doc = json.loads(self.path.read_text()) if self.path.exists() else {"core": 0.0, "virtual": {}, "days": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1))
        os.replace(tmp, self.path)

    def day(self, d: str) -> dict | None:
        return self.doc["days"].get(d)


class AlpacaBumi:
    """Bumi's own paper account."""

    def __init__(self):
        from alpaca.trading.client import TradingClient
        from app import settings
        settings.load_env()
        a = settings.alpaca_settings()                 # refuses anything but paper
        self.t = TradingClient(a.api_key, a.secret_key, paper=True)

    def equity(self) -> float:
        return float(self.t.get_account().equity)

    def positions(self) -> dict[str, int]:
        return {p.symbol: int(float(p.qty)) for p in self.t.get_all_positions()}

    def order(self, client_id: str) -> dict | None:
        from alpaca.common.exceptions import APIError
        try:
            o = self.t.get_order_by_client_id(client_id)
        except APIError:
            return None
        return {"status": getattr(o.status, "value", str(o.status)), "filled_qty": int(float(o.filled_qty or 0)),
                "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None}

    def close_all(self) -> None:
        self.t.close_all_positions(cancel_orders=True)

    def submit_opg(self, sym: str, side: str, qty: int, client_id: str) -> str:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        o = self.t.submit_order(MarketOrderRequest(symbol=sym, qty=qty, time_in_force=TimeInForce.OPG,
                                                   side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                                                   client_order_id=client_id))
        return getattr(o.status, "value", str(o.status))


def build_orders(plan: dict, s: dict, equity: float, held: dict[str, int], closes: dict[str, float],
                 old_core: float) -> tuple[list[Order], list[str]]:
    """Pure: the next open's orders, sells first. Dip orders follow the plan's buy and sell actions; the core trades
    only when its target weight changes, as in the backtest."""
    stamp, orders, notes = plan["as_of"].replace("-", ""), [], []

    def add(sym, side, qty, why):
        orders.append(Order(sym, side, qty, why, f"bumi-{stamp}-{sym}-{side}"))

    def shares(weight, sym):
        px = closes.get(sym)
        if not px or px <= 0:
            notes.append(f"{sym}: no price, order skipped")
            return None
        return math.floor(weight * equity * (1 - CASH_BUFFER) / px)

    for r in plan["rows"]:
        if r["action"] == "sell":
            q = held.get(r["etf"], 0)
            if q > 0:
                add(r["etf"], "sell", q, f"{r['sym']} stop or time exit")
            else:
                notes.append(f"{r['etf']}: plan says sell but nothing is held")
        elif r["action"] == "buy":
            if held.get(r["etf"], 0) > 0:
                notes.append(f"{r['etf']}: plan says buy but it is already held")
                continue
            q = shares(s["sizing"]["dip_weight"], r["etf"])
            if q:
                add(r["etf"], "buy", q, r["why"] or "dip")
    core = s["core"]["symbol"]
    new = plan["targets"].get(core, 0.0)
    if abs(new - old_core) > 1e-9:
        want = 0 if new == 0 else shares(new, core)
        if want is not None:
            d = want - held.get(core, 0)
            if d:
                add(core, "buy" if d > 0 else "sell", abs(d), f"core to {new:.0%}")
    orders.sort(key=lambda o: o.side != "sell")
    return orders, notes


def decide(plan: dict, s: dict, state: State, closes: dict[str, float], run_mode: str, broker=None) -> dict:
    """Save the plan and orders for the next open. Sends nothing. Running it twice for a day changes nothing."""
    day = plan["as_of"]
    if state.day(day):
        return state.day(day)
    if run_mode == "paper":
        equity, held = broker.equity(), broker.positions()
    else:
        held = dict(state.doc["virtual"])
        equity = float(s["account"]["size_usd"])
    orders, notes = build_orders(plan, s, equity, held, closes, state.doc["core"])
    rec = {"plan": plan, "orders": [asdict(o) for o in orders], "notes": notes, "mode": run_mode, "sent": False,
           "confirmed": False, "next_core": plan["targets"].get(s["core"]["symbol"], 0.0)}
    if run_mode != "paper":                            # shadow keeps a virtual book, so its sells have shares
        for o in orders:
            q = held.get(o.sym, 0) + (o.qty if o.side == "buy" else -o.qty)
            if q > 0:
                held[o.sym] = q
            else:
                held.pop(o.sym, None)
        state.doc["virtual"] = held
        state.doc["core"] = rec["next_core"]
    state.doc["days"][day] = rec
    state.save()
    return rec


def send(prev_session: str, now: datetime, state: State, run_mode: str, broker=None, paused: bool = False) -> list[str]:
    """Send the previous session's orders. Only in paper mode, only inside the market-on-open window, only once."""
    rec = state.day(prev_session)
    if rec is None:
        return [f"no plan for {prev_session}, nothing sent"]
    if run_mode != "paper" or rec.get("mode") != "paper":
        return ["shadow mode, nothing sent"]
    if rec["sent"]:
        return ["already sent"]
    if rec.get("cancelled"):
        return ["cancelled by a flatten, nothing sent"]
    if paused:
        return ["paused, nothing sent"]
    t = now.astimezone(NY).time()
    if not SEND_AT <= t <= LAST_SEND:
        return [f"outside the send window at {t:%H:%M}, nothing sent"]
    out = []
    for o in rec["orders"]:
        try:
            have = broker.order(o["client_id"])
            if have:
                o["status"] = have["status"]
            else:
                o["status"] = broker.submit_opg(o["sym"], o["side"], o["qty"], o["client_id"])
        except Exception as e:  # noqa: BLE001 - one failed order is reported and must not stop the others
            o["status"] = f"failed: {type(e).__name__}"
            out.append(f"{o['sym']} {o['side']} failed")
        state.save()
    rec["sent"] = True
    state.doc["core"] = rec["next_core"]
    state.save()
    return out


def confirm(prev_session: str, state: State, broker) -> list[str]:
    """After the open: every order filled in full? Returns the problems (empty is clean)."""
    rec = state.day(prev_session)
    if rec is None or rec.get("mode") != "paper" or not rec["sent"]:
        return []
    problems = []
    for o in rec["orders"]:
        have = broker.order(o["client_id"])
        if not have:
            problems.append(f"{o['sym']} {o['side']}: order not found")
            continue
        o["status"], o["filled_qty"], o["filled_price"] = have["status"], have["filled_qty"], have["filled_price"]
        if have["status"] != "filled" or have["filled_qty"] != o["qty"]:
            problems.append(f"{o['sym']} {o['side']}: {have['status']}, {have['filled_qty']}/{o['qty']} filled")
    rec["confirmed"] = True
    state.save()
    return problems


def flatten(state: State, run_mode: str, broker=None) -> str:
    """The kill switch: cancel unsent plans, cancel open orders and close everything in Bumi's own account."""
    for rec in state.doc["days"].values():
        if not rec["sent"]:
            rec["cancelled"] = True
    state.doc["core"] = 0.0
    if run_mode != "paper":
        state.doc["virtual"] = {}
        state.save()
        return "shadow mode, nothing to close"
    state.save()
    held = broker.positions()
    broker.close_all()
    return f"closing {len(held)} position{'' if len(held) == 1 else 's'}" if held else "nothing was open"


def align(bars_by_sym: dict[str, list[D]], vix_series: dict[date, float], expect: date,
          vix_ok: bool) -> tuple[dict[str, list[D]], list[float], bool]:
    """Bars on shared dates through `expect`, the VIX on those dates, and whether it is safe to buy on it."""
    days = set.intersection(*({b.t.date() for b in v} for v in bars_by_sym.values()))
    days = {d for d in days if d <= expect}
    if expect not in days:
        raise ValueError(f"final bars for {expect} are missing")
    out = {u: [b for b in v if b.t.date() in days] for u, v in bars_by_sym.items()}
    last, vix = 20.0, []
    for d in sorted(days):
        last = vix_series.get(d, last)
        vix.append(last)
    return out, vix, vix_ok and expect in vix_series
