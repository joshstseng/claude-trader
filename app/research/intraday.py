"""Intraday strategies for the research lab (regular hours, 9:30–16:00 ET, flat at the close).

noise_breakout: the "noise area" intraday momentum strategy (Zarattini, Aziz & Barbon, 2024, "Beat the Market"):
    for each minute of the day, sigma(m) = the average over the last `lookback` days of |close at m / open − 1|.
    Upper = max(open, previous close) × (1 + band × sigma(m)); lower = min(open, previous close) × (1 − band × sigma(m)).
    At each check (every `every` minutes from 10:00): above the upper -> long, below the lower -> short.
    The stop trails at the band (and at VWAP when there's volume); it's checked at the same times. Flat at 16:00.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from app.research.data import D
from app.research.evaluate import ACCOUNT, RISK, Trade

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = dtime(9, 30), dtime(16, 0)


def sessions(bars: list[D]) -> dict[date, list[tuple[int, D]]]:
    """Regular-hours bars by NY date as (minutes since 9:30, bar)."""
    out: dict[date, list] = defaultdict(list)
    for b in bars:
        t = b.t.astimezone(NY)
        m = (t.hour * 60 + t.minute) - (9 * 60 + 30)
        if 0 <= m < 390:
            out[t.date()].append((m, b))
    return dict(sorted(out.items()))


def noise_breakout(sym: str, bars: list[D], *, step: int = 5, lookback: int = 14, every: int = 30,
                   band: float = 1.0, use_vwap: bool = True, slip_bp: float = 1.0, commission: float = 0.0,
                   sizing: str = "vol", target_vol: float = 0.02, max_lev: float = 4.0, risk_stop_sig: float = 1.0,
                   first_check: int = 30, allow_short: bool = True, point_value: float | None = None,
                   per_side: float = 0.0, max_contracts: int = 50) -> list[Trade]:
    """point_value (futures, e.g. MNQ 2.0): whole contracts, `per_side` $ per contract per side (commission +
    slippage) instead of slip_bp; qty in the Trade is contracts × point_value."""
    days = sessions(bars)
    keys = list(days)
    hist: deque = deque(maxlen=lookback)        # per day: {minute: |close/open - 1|}
    rets: deque = deque(maxlen=14)              # daily close-to-close returns, for vol sizing
    out: list[Trade] = []
    prev_close = None
    for d in keys:
        rows = days[d]
        if len(rows) < 390 // step * 0.8:
            prev_close = rows[-1][1].c if rows else prev_close
            continue
        o = rows[0][1].o
        move = {m + step: abs(b.c / o - 1) for m, b in rows}          # at the END of each bar
        if len(hist) == lookback and prev_close:
            sig = {m: sum(h.get(m, 0.0) for h in hist) / lookback for m in move}
            up_ref, dn_ref = max(o, prev_close), min(o, prev_close)
            vol = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else 0.01
            pos, p_in, t_in, qty = 0, 0.0, None, 0.0
            pv = vv = 0.0
            for m, b in rows:
                end = m + step
                typ = (b.h + b.l + b.c) / 3
                pv += typ * (b.v or 1.0)
                vv += (b.v or 1.0)
                vwap = pv / vv
                if end < first_check or end % every and end != 390:
                    continue
                s = sig.get(end)
                if s is None:
                    continue
                up, dn = up_ref * (1 + band * s), dn_ref * (1 - band * s)
                px = b.c
                if pos:                                                   # trailing stop at the band / VWAP
                    stop = (max(up, vwap) if use_vwap else up) if pos > 0 else (min(dn, vwap) if use_vwap else dn)
                    if end == 390 or (px < stop if pos > 0 else px > stop):
                        if point_value:
                            out.append(Trade(sym, pos, t_in, b.t, p_in, px, qty, 2 * per_side * qty / point_value))
                        else:
                            p_out = px * (1 - pos * slip_bp / 1e4)
                            out.append(Trade(sym, pos, t_in, b.t, p_in, p_out, qty, 2 * commission * qty))
                        pos = 0
                if not pos and end < 390:
                    want = 1 if px > up else (-1 if px < dn and allow_short else 0)
                    if want:
                        p_in = px if point_value else px * (1 + want * slip_bp / 1e4)
                        if point_value:
                            lev = min(max_lev, target_vol / max(vol, 1e-4))
                            n = int(ACCOUNT * lev / (p_in * point_value))
                            if sizing == "risk":
                                n = int(RISK * ACCOUNT / (risk_stop_sig * s * p_in * point_value))
                            n = min(n, max_contracts)
                            if n < 1:
                                continue
                            qty = n * point_value
                        elif sizing == "vol":
                            qty = ACCOUNT * min(max_lev, target_vol / max(vol, 1e-4)) / p_in
                        else:                                             # 1% risk to a stop risk_stop_sig x sigma away
                            qty = min(RISK * ACCOUNT / (risk_stop_sig * s * p_in), max_lev * ACCOUNT / p_in)
                        pos, t_in = want, b.t
        hist.append(move)
        if prev_close:
            rets.append(rows[-1][1].c / prev_close - 1)
        prev_close = rows[-1][1].c
    return out
