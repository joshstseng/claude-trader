"""Swing v1.1's intraday routine, a separate bot from Bumi and Orbi. app/swing_run.py runs it.

    from 9:00 AM ET   read prior sessions and save today's context
    during the day    process each completed 5-minute bar once, then trade toward Swing v1.1's wanted position
    3:58:45 PM ET     flat, whatever the signal says
    after the close   compare paper fills with the v1.1 and v1 models

SWING_MODE=paper is the only value that can send orders. Anything else is shadow. One order is in flight at a time, and
client order ids make a retried send harmless. Exits still run while paused; new entries do not.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app import paths
from app.settings import _read_json
from app.strategies.swing import BARS, Machine, context

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
PREPARE_AT = dtime(9, 0)
GRACE_S = 3
MISSING_BAR_WAIT_S = 45
SUMMARY_AT = dtime(16, 5)
STATE_FILE = paths.bot_dir("swing") / "data" / "swing_state.json"


def mode() -> str:
    return "paper" if (os.environ.get("SWING_MODE") or "").strip().lower() == "paper" else "shadow"


def load_settings() -> dict:
    return _read_json(paths.STRATEGY_CONFIG_DIR / "swing.json")


class State:
    """Swing's saved days and ledger. Written atomically, so a crash can't leave half a file."""

    def __init__(self, path: Path = STATE_FILE):
        self.path = Path(path)
        self.doc = json.loads(self.path.read_text()) if self.path.exists() else {"days": {}}
        self.doc.setdefault("ledger", {"open": None, "closed": [], "fills": []})
        self.doc.setdefault("seq", 0)

    @property
    def ledger(self) -> dict:
        return self.doc["ledger"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1))
        os.replace(tmp, self.path)

    def day(self, d: str) -> dict | None:
        return self.doc["days"].get(d)


class AlpacaSwing:
    """Swing's own paper account."""

    def __init__(self, symbol: str):
        from alpaca.trading.client import TradingClient
        from app import settings
        settings.load_env()
        a = settings.alpaca_settings()                 # refuses anything but paper
        self.t = TradingClient(a.api_key, a.secret_key, paper=True)
        self.symbol = symbol

    def equity(self) -> float:
        return float(self.t.get_account().equity)

    def position(self) -> tuple[int, float | None]:
        """Signed shares (shorts are negative) and the current price."""
        for p in self.t.get_all_positions():
            if p.symbol == self.symbol:
                q = abs(int(float(p.qty)))
                short = "short" in str(getattr(p.side, "value", p.side)).lower()
                return (-q if short else q), float(p.current_price) if p.current_price else None
        return 0, None

    def order(self, client_id: str) -> dict | None:
        from alpaca.common.exceptions import APIError
        try:
            o = self.t.get_order_by_client_id(client_id)
        except APIError:
            return None
        return {"status": getattr(o.status, "value", str(o.status)), "filled_qty": int(float(o.filled_qty or 0)),
                "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None}

    def submit(self, side: str, qty: int, client_id: str) -> str:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        o = self.t.submit_order(MarketOrderRequest(symbol=self.symbol, qty=qty, time_in_force=TimeInForce.DAY,
                                                   side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                                                   client_order_id=client_id))
        return getattr(o.status, "value", str(o.status))

    def close_all(self) -> None:
        self.t.close_all_positions(cancel_orders=True)


def matrix(rows: list[tuple[datetime, float, float, float, float]]):
    """(time, o, h, l, c) rows into N x 78 arrays of full regular sessions, using the backtest's session filter."""
    if not rows:
        return pd.DatetimeIndex([]), *(np.empty((0, BARS)) for _ in range(4))
    x = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c"])
    t = pd.to_datetime(x.t, utc=True).dt.tz_convert(NY)
    x["d"] = t.dt.tz_localize(None).dt.normalize()
    x["k"] = (t.dt.hour * 60 + t.dt.minute - 570) // 5
    x = x[(x.k >= 0) & (x.k < BARS)]
    n, last = x.groupby("d").k.count(), x.groupby("d").k.max()
    days = pd.DatetimeIndex(sorted(n[(n >= 70) & (last >= BARS - 1)].index))
    x = x[x.d.isin(days)]
    pos = pd.Series(np.arange(len(days)), index=days)
    A = {c: np.full((len(days), BARS), np.nan) for c in "ohlc"}
    for c in "ohlc":
        A[c][x.d.map(pos).to_numpy(), x.k.to_numpy()] = x[c].to_numpy()
    C = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy()
    return days, *(np.where(np.isnan(A[c]), C, A[c]) for c in "ohl"), C


def today_arrays(rows, through: int):
    """Today's bars through `through`, filling a bar with no trades from the last close."""
    O, H, L, C = (np.full(BARS, np.nan) for _ in range(4))
    for t, o, h, l, c in rows:
        x = t.astimezone(NY); k = (x.hour * 60 + x.minute - 570) // 5
        if 0 <= k <= through:
            O[k], H[k], L[k], C[k] = o, h, l, c
    if np.isnan(C[:through + 1]).all():
        return None
    filled = pd.Series(C[:through + 1]).ffill().bfill().to_numpy()
    C[:through + 1] = filled
    for a in (O, H, L):
        a[:through + 1] = np.where(np.isnan(a[:through + 1]), filled, a[:through + 1])
    return O, H, L, C


def last_done_bar(now: datetime, session) -> int:
    return min(int(((now - session.at(session.open)).total_seconds() - GRACE_S) // 300) - 1, BARS - 1)


def numbers(state: State) -> dict:
    """Realized results for Uri's fleet summary."""
    led, days = state.ledger, {}

    def day(d):
        return days.setdefault(d, {"orders": 0, "filled": 0, "closed": 0, "wins": 0, "day_pnl": 0.0})
    for f in led["fills"]:
        x = day(f["day"])
        x["orders"] += 1
        x["filled"] += 1
    for t in led["closed"]:
        x = day(t["day"])
        x["closed"] += 1
        x["wins"] += t["pnl"] > 0
        x["day_pnl"] = round(x["day_pnl"] + t["pnl"], 2)
    return {"days": days, "all_time": round(sum(t["pnl"] for t in led["closed"]), 2), "all_trades": len(led["closed"]),
            "open": 1 if led["open"] else 0, "at_risk": 0.0}


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def live_text(lot: dict, sym: str, px: float | None) -> tuple[str, int]:
    now = px if px is not None else lot["entry"]
    pnl = lot["side"] * (now - lot["entry"]) * lot["qty"]
    pct = lot["side"] * (now / lot["entry"] - 1) * 100
    name = "LONG" if lot["side"] > 0 else "SHORT"
    text = (f"🟢 **{sym} {name}** · Swing v1.1 · **{_usd(pnl)}** ({pct:+.2f}%)\n{lot['qty']} sh · in ${lot['entry']:,.2f} at "
            f"{lot['time']} ET · " + (f"now ${px:,.2f}" if px is not None else "price unavailable")
            + f"\nEntry: {lot['why']}\nExits: 15m FVG break, 30m band check, or flat by the close.")
    return text, 0x2ECC71 if pnl >= 0 else 0xE74C3C


def closed_text(t: dict, sym: str) -> tuple[str, int]:
    icon = "✅" if t["pnl"] > 0 else "❌" if t["pnl"] < 0 else "➖"
    name = "LONG" if t["side"] > 0 else "SHORT"
    pct = t["side"] * (t["exit"] / t["entry"] - 1) * 100
    text = (f"{icon} **{sym} {name}** · Swing v1.1 · **{_usd(t['pnl'])}** ({pct:+.2f}%)\nIn ${t['entry']:,.2f} ({t['time_in']}) → "
            f"out ${t['exit']:,.2f} ({t['time_out']} ET) · {t['qty']} sh\nExit: {t['why']}")
    return text, 0x2ECC71 if t["pnl"] > 0 else 0xE74C3C if t["pnl"] < 0 else 0x95A5A6


def live_ping(lot: dict, sym: str, owner_id: int) -> str:
    """The @mention line on a new live card. It stays fixed while the embed's P&L refreshes."""
    return f"<@{owner_id}> 🟢 **{sym} {'LONG' if lot['side'] > 0 else 'SHORT'}** · Swing v1.1"


def closed_message(t: dict, sym: str, owner_id: int) -> tuple[str, str, int]:
    """(message with the @mention and headline, embed body, color), laid out like Orbi's closed cards."""
    text, color = closed_text(t, sym)
    head, body = text.split("\n", 1)
    return f"<@{owner_id}> {head}", body, color


MORNING_LINES = {
    "wild": ("Market's looking wild today. Smaller size, same discipline.",
             "Big swings out here. I'm sizing down and waiting for the real move.",
             "Choppy seas this morning. Show me a clean break and we ride."),
    "gap_up": ("Bulls showed up early. Hold {up} and maybe we catch the run.",
               "Gapped up and feeling frisky. {up} is the level to clear.",
               "Green open, eyes on {up}. Let's see if it has legs."),
    "gap_down": ("Bears came in swinging. Lose {down} and I'm short.",
                 "Rough open. {down} decides if this gets ugly.",
                 "Red out of the gate, eyes on {down}. Let's see who blinks."),
    "steady": ("Watching {up} and {down} closely. Here's the rundown:",
               "Quiet open. I'm not moving until {up} or {down} breaks.",
               "Patience mode. Give me {up} or {down} and we go."),
}


def morning_text(key: str, sym: str, first_open: float, m: dict, prev: float, reference_usd: float) -> str:
    """Swing's short card after the first bar. Levels are the 10:00 check's; it changes no trading decision."""
    day = date.fromisoformat(key)
    up, down, weight = m["up"][5], m["down"][5], m["weight"]
    gap = first_open / prev - 1
    mood = "wild" if weight < .6 else "gap_up" if gap >= .005 else "gap_down" if gap <= -.005 else "steady"
    options = MORNING_LINES[mood]
    line = options[day.toordinal() % len(options)].format(up=f"${up:,.2f}", down=f"${down:,.2f}")
    qty = math.floor(weight * reference_usd / first_open)
    return (f"🎯 **Swing's rundown · {day:%a %b %d}**\n*{line}*\n\n📈 {sym} long above **${up:,.2f}**\n"
            f"📉 {sym} short below **${down:,.2f}**\n📦 Size: **{qty:,} shares** (about ${qty * first_open:,.0f}, {weight:.2f}x)\n"
            "-# Levels are for the 10:00 AM ET check and shift through the day. Between them, I stay flat.")


class Routine:
    """One tick of Swing's day. Everything external is passed in, so tests run it on a fake clock and broker."""

    def __init__(self, s, state, calendar, broker, history, today, post, report, paused, run_mode):
        self.s, self.state, self.cal, self.broker, self.history, self.today = s, state, calendar, broker, history, today
        self.post, self.report, self.paused, self.mode = post, report, paused, run_mode
        self.sym = s["symbol"]
        self.flat_at = dtime.fromisoformat(s["flat_at"])
        self.ref = float(s["sizing"]["reference_usd"])
        self.cost = float(s["costs"]["model_bp_per_side"])
        self.sessions: dict[date, object] = {}
        self.retry_at: datetime | None = None
        self.warned: set[str] = set()

    def session(self, d: date):
        if d not in self.sessions:
            self.sessions[d] = self.cal.session(d)
        return self.sessions[d]

    def warn_once(self, key: str, text: str, ping: bool = True) -> None:
        if key not in self.warned:
            self.warned.add(key)
            self.post("system", text, ping)

    def tick(self, now: datetime) -> None:
        t = now.astimezone(NY)
        session = self.session(t.date())
        if not session or t.time() < PREPARE_AT:
            return
        key = t.date().isoformat()
        rec = self.state.day(key)
        if rec is None:
            rec = self.prepare(key, t, session)
            if rec is None:
                return
        if t < session.at(session.open):
            return
        if not rec.get("skip"):
            self.advance(rec, key, t, session)
        if self.mode == "paper":
            self.trade(rec, key, t, session)
        if t.time() >= SUMMARY_AT and not rec.get("summary"):
            self.finish(rec, key, t)

    def prepare(self, key: str, t: datetime, session) -> dict | None:
        if session.early_close or session.open != dtime(9, 30):
            rec = {"skip": "shortened session", "pending": None, "summary": False}
            self.state.doc["days"][key] = rec
            self.state.save()
            self.post("system", f"⏭️ **Swing v1.1 is off today** ({key}): shortened sessions were not part of its backtest.", False)
            return rec
        if self.retry_at and t < self.retry_at:
            return None
        try:
            days, O, H, L, C = self.history(t.date())
            keep = days < pd.Timestamp(t.date())
            ctx = context(O[keep], H[keep], L[keep], C[keep], self.s["sizing"]["daily_vol_target"], self.s["sizing"]["max_exposure"])
        except Exception as e:  # noqa: BLE001 - no context means no trades, and it keeps retrying
            log.exception("couldn't prepare %s", key)
            self.retry_at = t + timedelta(seconds=60)
            if t >= session.at(session.open):
                self.warn_once(f"{key}:context", f"⚠️ **Swing v1.1 has no setup for {key}** ({type(e).__name__}). No new trades until it can read history.")
            return None
        self.retry_at = None
        rec = {"context": ctx, "v11": None, "v1": None, "pending": None, "halted": False, "missed": -1, "summary": False}
        self.state.doc["days"][key] = rec
        self.state.save()
        return rec

    def advance(self, rec: dict, key: str, t: datetime, session) -> None:
        k = last_done_bar(t, session)
        nxt = rec["v11"]["next_bar"] if rec["v11"] else 0
        if k < nxt:
            return
        try:
            rows = self.today(t.date())
        except Exception as e:  # noqa: BLE001
            log.warning("today's bars failed: %s", e)
            self.warn_once(f"{key}:data", f"⚠️ **Swing v1.1 can't read live bars** ({type(e).__name__}). Still retrying; it will be flat by the close.")
            return
        have = any((x.astimezone(NY).hour * 60 + x.astimezone(NY).minute - 570) // 5 == k for x, *_ in rows)
        if not have and t < session.at(session.open) + timedelta(seconds=(k + 1) * 300 + MISSING_BAR_WAIT_S):
            return
        got = today_arrays(rows, k)
        if got is None:
            return
        O, H, L, C = got
        if rec["v11"] is None:
            rec["v11"] = Machine.start(rec["context"], float(O[0]), True, self.cost).to_dict()
            rec["v1"] = Machine.start(rec["context"], float(O[0]), False, self.cost).to_dict()
        a, b = Machine(**rec["v11"]), Machine(**rec["v1"])
        for bar in range(a.next_bar, k + 1):
            a.step(bar, O, H, L, C)
            b.step(bar, O, H, L, C)
        rec["v11"], rec["v1"], rec["last_close"], rec["done_bar"] = a.to_dict(), b.to_dict(), float(C[k]), k
        send_morning = not rec.get("morning") and t < session.at(dtime(10, 0))
        rec["morning"] = rec.get("morning") or send_morning   # saved first, so a restart can't post it twice
        self.state.save()
        if send_morning:
            try:
                self.post("setups", morning_text(key, self.sym, float(O[0]), rec["v11"], rec["context"]["prev"], self.ref), False)
            except Exception:  # noqa: BLE001 - a card must never get in the way of trading
                log.warning("couldn't post Swing's morning card", exc_info=True)

    def morning_preview(self, key: str) -> str:
        """Post a finished day's morning card on request. It reads saved levels only and never touches trading."""
        rec = self.state.day(key)
        if not rec or not rec.get("v11"):
            return f"no levels saved for {key}"
        got = today_arrays(self.today(date.fromisoformat(key)), 0)
        if got is None:
            return f"no opening bar for {key}"
        text = morning_text(key, self.sym, float(got[0][0]), rec["v11"], rec["context"]["prev"], self.ref)
        self.post("setups", f"{text}\n-# Preview of this morning's card", False)
        return "posted the morning card preview"

    def target(self, rec: dict, t: datetime, session) -> int:
        if rec.get("skip") or rec.get("halted") or not rec.get("v11") or t.time() >= self.flat_at:
            return 0
        return int(rec["v11"]["side"])

    def trade(self, rec: dict, key: str, t: datetime, session) -> None:
        if rec.get("pending"):
            self.poll(rec, key, t)
            if rec.get("pending"):
                return
        try:
            pos, px = self.broker.position()
        except Exception:  # noqa: BLE001
            log.warning("couldn't read the position", exc_info=True)
            return
        self.reconcile(pos, px, rec, key, t)
        want = self.target(rec, t, session)
        if pos and (want == 0 or (pos > 0) != (want > 0)):
            why = (rec.get("v11") or {}).get("why") or "flat"
            if t.time() >= self.flat_at:
                why = "flat by the close"
            elif rec.get("halted"):
                why = "flatten"
            self.send(rec, key, t, "sell" if pos > 0 else "buy", abs(pos), "exit", why)
        elif not pos and want and t < session.at(self.flat_at):
            m = rec["v11"]
            if m["signal_bar"] == rec.get("missed"):
                return
            if self.paused():
                rec["missed"] = m["signal_bar"]
                self.state.save()
                self.post("system", "⏸️ Swing v1.1 is paused, so it skipped a new entry.", False)
                return
            if rec.get("done_bar", -1) - m["signal_bar"] > 1:
                rec["missed"] = m["signal_bar"]
                self.state.save()
                self.post("system", "⏭️ Swing v1.1 skipped an entry because the signal was more than one bar old.", True)
                return
            qty = math.floor(m["weight"] * self.ref / rec["last_close"])
            if qty >= 1:
                self.send(rec, key, t, "buy" if want > 0 else "sell", qty, "entry", m["why"])

    def send(self, rec: dict, key: str, t: datetime, side: str, qty: int, kind: str, why: str) -> None:
        self.state.doc["seq"] += 1
        cid = f"swing-{key.replace('-', '')}-{self.state.doc['seq']:04d}"
        rec["pending"] = {"id": cid, "side": side, "qty": qty, "kind": kind, "why": why, "at": t.isoformat()}
        self.state.save()                   # saved first, so a crash can't send the same decision under a new id
        try:
            self.broker.submit(side, qty, cid)
        except Exception as e:  # noqa: BLE001
            log.exception("order failed")
            try:
                have = self.broker.order(cid)
            except Exception:  # noqa: BLE001
                return                       # unknown: keep it pending and check again next tick
            if not have:
                rec["pending"] = None
                self.state.save()
                self.warn_once(f"{key}:order:{cid}", f"⚠️ **Swing v1.1 order failed:** {side} {qty} {self.sym} ({type(e).__name__}). It will retry if still wanted.")

    def poll(self, rec: dict, key: str, t: datetime) -> None:
        p = rec["pending"]
        try:
            o = self.broker.order(p["id"])
        except Exception:  # noqa: BLE001
            log.warning("order check failed", exc_info=True)
            return
        age = (t - datetime.fromisoformat(p["at"])).total_seconds()
        if o is None:
            if age >= 30:
                rec["pending"] = None
                self.state.save()
                self.warn_once(f"{key}:missing:{p['id']}", f"⚠️ **Swing v1.1:** order {p['id']} was not found at Alpaca.")
            return
        if o["status"] == "filled" or o["status"] in ("canceled", "expired", "rejected", "done_for_day"):
            if o["filled_qty"] and o["filled_price"]:
                self.book(p["side"], o["filled_qty"], o["filled_price"], key, t, p["why"])
            if o["status"] != "filled":
                self.post("system", f"⚠️ **Swing v1.1 order {o['status']}:** {p['side']} {p['qty']} {self.sym}, filled {o['filled_qty']}.", True)
            rec["pending"] = None
            self.state.save()
        elif age >= 120:
            self.warn_once(f"{key}:slow:{p['id']}", f"⚠️ **Swing v1.1:** {p['side']} {p['qty']} {self.sym} is still {o['status']} after 2 minutes.")

    def book(self, side: str, qty: int, price: float, key: str, t: datetime, why: str) -> None:
        led = self.state.ledger
        now = t.astimezone(NY).strftime("%H:%M:%S")
        led["fills"].append({"day": key, "time": now, "side": side, "qty": qty, "price": price})
        sign = 1 if side == "buy" else -1
        lot = led["open"]
        if lot is None:
            led["open"] = {"side": sign, "qty": qty, "entry": price, "time": now, "day": key, "why": why, "card": None}
            return
        if lot["side"] == sign:
            lot["entry"] = (lot["entry"] * lot["qty"] + price * qty) / (lot["qty"] + qty)
            lot["qty"] += qty
            return
        q = min(qty, lot["qty"])
        led["closed"].append({"day": key, "side": lot["side"], "qty": q, "entry": lot["entry"], "exit": price,
                              "pnl": round(lot["side"] * (price - lot["entry"]) * q, 2), "time_in": lot["time"], "time_out": now,
                              "why": why, "card_posted": False, "live_card": lot.get("card") if q == lot["qty"] else None})
        lot["qty"] -= q
        if lot["qty"] <= 0:
            led["open"] = None

    def reconcile(self, pos: int, px: float | None, rec: dict, key: str, t: datetime) -> None:
        lot = self.state.ledger["open"]
        have = lot["side"] * lot["qty"] if lot else 0
        if pos == have:
            return
        if pos == 0 and lot:
            price = px or rec.get("last_close") or lot["entry"]
            self.book("sell" if lot["side"] > 0 else "buy", lot["qty"], price, key, t, "closed outside the bot (estimated price)")
            self.state.save()
            self.post("system", f"⚠️ **Swing v1.1:** the {self.sym} position was closed outside the bot. P&L uses an estimated price.", True)
        else:
            self.warn_once(f"{key}:mismatch:{pos}:{have}", f"⚠️ **Swing v1.1 position mismatch:** Alpaca shows {pos}, its records show {have}.")

    def finish(self, rec: dict, key: str, t: datetime) -> None:
        if rec.get("skip"):
            rec["summary"] = True
            self.state.save()
            return
        if rec.get("v11") and rec["v11"]["next_bar"] < BARS and t.time() < dtime(16, 20):
            return
        day = [x for x in self.state.ledger["closed"] if x["day"] == key]
        paper = sum(x["pnl"] for x in day)
        m11, m1 = rec.get("v11") or {"pnl": 0, "trades": 0}, rec.get("v1") or {"pnl": 0, "trades": 0}
        text = (f"📊 **Swing v1.1 · {key}**\nPaper: **{_usd(paper)}** · {len(day)} closed trade{'' if len(day) == 1 else 's'} · {self.mode} mode\n"
                f"Model v1.1: {_usd(m11['pnl'] * self.ref)} ({m11['trades']} trades)\nModel v1 baseline: {_usd(m1['pnl'] * self.ref)} ({m1['trades']} trades)")
        try:
            self.report(key, text)
            self.post("system", text, False)
            rec["summary"] = True
            self.state.save()
        except Exception:  # noqa: BLE001
            log.warning("couldn't post the daily summary", exc_info=True)

    def flatten(self, today: str) -> str:
        """The kill switch: stop today's trading, cancel orders and close Swing's own account."""
        rec = self.state.day(today)
        if rec is not None:
            rec["halted"] = True
            rec["pending"] = None
        self.state.save()
        if self.mode != "paper":
            return "shadow mode, nothing to close"
        pos, _ = self.broker.position()
        self.broker.close_all()
        return f"closing {abs(pos)} {self.sym}" if pos else "nothing was open"

    def status_text(self, today: str) -> str:
        rec = self.state.day(today)
        if not rec:
            return f"{self.mode} mode · waiting for the session"
        if rec.get("skip"):
            return f"{self.mode} mode · off today ({rec['skip']})"
        m = rec.get("v11")
        side = {1: "long", -1: "short", 0: "flat"}[m["side"]] if m else "before the open"
        return f"{self.mode} mode · Swing v1.1 {side} · bar {m['next_bar'] if m else 0}/{BARS}"
