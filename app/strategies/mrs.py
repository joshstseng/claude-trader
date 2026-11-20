"""Mr. S: Bollinger mean-reversion on NQ futures (MNQ), Asia session first. Plan: plans/mrs-strategy.md

Version A, "trend pullback" (the one built so far):
    1h   RSI(14) > 55 -> longs only, < 45 -> shorts only (indicators.rsi_minutes)
    15m  ADX(14) > 20 (trending) (indicators.adx_minutes)
    5m   a bar CLOSES outside the Bollinger Band (20, 2): below the lower band for a long, above the upper for a short
    5m   within the next 2 bars, the first bar with any part of its BODY back inside the band -> enter at its close
    stop the extreme of the cross bar and the entry bar (lowest low for a long), plus a small buffer
    exit the middle band (moves each bar) or 2R, whichever comes first; the stop first if a bar hits both;
         everything flat at the session end
    risk 1% of the account per trade (whole contracts); the session stops after a 2R loss; one trade at a time

Everything here is pure: bars in, setups and trades out. The live bot (Discord, Tradovate) and the backtest
scenarios come later. Times: bars are tagged by their START; a 5m bar's values are known at start + 5 min.
NQ and MNQ trade at the same price, so NQ bars test MNQ (only the dollars per point differ).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
FIVE = timedelta(minutes=5)


@dataclass(frozen=True)
class Bar:
    start: datetime   # timezone-aware
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


# ------------------------------------------------------------------ indicators

def bollinger(closes: list[float], n: int = 20, k: float = 2.0) -> list[tuple[float, float, float] | None]:
    """(lower, middle, upper) per bar; None until n bars. Population standard deviation (as TradingView)."""
    out: list[tuple[float, float, float] | None] = []
    for i in range(len(closes)):
        if i + 1 < n:
            out.append(None)
            continue
        w = closes[i + 1 - n:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        out.append((m - k * sd, m, m + k * sd))
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI; None until n changes are known."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n

    def value(g, l):
        return 100.0 if l == 0 else 100.0 - 100.0 / (1 + g / l)
    out[n] = value(ag, al)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = value(ag, al)
    return out


def adx(bars: list[Bar], n: int = 14) -> list[float | None]:
    """Wilder's ADX; None for the first 2n - 1 bars."""
    out: list[float | None] = [None] * len(bars)
    if len(bars) < 2 * n:
        return out
    tr, pdm, mdm = [], [], []
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        up, down = b.h - p.h, p.l - b.l
        tr.append(max(b.h - b.l, abs(b.h - p.c), abs(b.l - p.c)))
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
    atr, sp, sm = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs = []
    for j in range(n - 1, len(tr)):
        if j >= n:
            atr = atr - atr / n + tr[j]
            sp = sp - sp / n + pdm[j]
            sm = sm - sm / n + mdm[j]
        pdi = 100 * sp / atr if atr else 0.0
        mdi = 100 * sm / atr if atr else 0.0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    a = sum(dxs[:n]) / n
    out[2 * n - 1] = a                   # dxs[k] belongs to bar k + n
    for k in range(n, len(dxs)):
        a = (a * (n - 1) + dxs[k]) / n
        out[k + n] = a
    return out


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """5m -> 15m (or any multiple), aligned to the clock; only complete buckets."""
    step = minutes // 5
    out, bucket = [], []
    for b in bars:
        key = b.start.replace(minute=b.start.minute - b.start.minute % minutes, second=0, microsecond=0)
        if bucket and bucket[0][0] != key:
            out.append(bucket)
            bucket = []
        bucket.append((key, b))
    if bucket:
        out.append(bucket)
    return [Bar(g[0][0], g[0][1].o, max(x.h for _, x in g), min(x.l for _, x in g), g[-1][1].c,
                sum(x.v for _, x in g)) for g in out if len(g) == step]


# ------------------------------------------------------------------ the session

def session_bounds(day: date, s: dict) -> tuple[datetime, datetime]:
    """The session that starts on `day` (Pacific time), e.g. 4:00 PM to 10:00 PM PT."""
    tz = ZoneInfo(s["session"]["tz"])
    start = datetime.combine(day, dtime.fromisoformat(s["session"]["start"]), tzinfo=tz)
    end = datetime.combine(day, dtime.fromisoformat(s["session"]["end"]), tzinfo=tz)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def contracts_for(stop_pts: float, s: dict) -> int:
    """Whole contracts so the loss at the stop (with costs) is at most risk_pct of the account."""
    acct, c = s["account"], s["contract"]
    per = stop_pts * c["point_value"] + _cost_per_contract(s)
    n = int(acct["size_usd"] * acct["risk_pct"] / per) if per > 0 else 0
    return min(n, acct["max_contracts"])


def _cost_per_contract(s: dict) -> float:
    """Round trip: commission both sides + slippage on the entry and on a stop exit."""
    c, k = s["contract"], s["costs"]
    return 2 * k["commission_per_side"] + 2 * k["slippage_ticks"] * c["tick"] * c["point_value"]


@dataclass
class Trade:
    side: str                     # long / short
    cross_at: str                 # the 5m bar that closed outside the band
    entry_at: str                 # the bar whose close is the entry
    entry: float
    stop: float
    target_2r: float
    middle_at_entry: float
    contracts: int
    rsi: float                    # on the RSI chart (indicators.rsi_minutes, e.g. 1h)
    adx: float                    # on the ADX chart (indicators.adx_minutes, e.g. 15m)
    exit_at: str | None = None
    exit: float | None = None
    result: str | None = None     # middle / 2R / stop / session_end
    r: float | None = None        # after costs
    pnl_usd: float | None = None  # after costs
    cost_usd: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionResult:
    day: str
    start: str
    end: str
    trades: list[Trade] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)   # {"at", "side", "why"}
    stopped_for_loss: bool = False

    @property
    def pnl_usd(self) -> float:
        return round(sum(t.pnl_usd or 0 for t in self.trades), 2)


def _round_tick(x: float, tick: float, down: bool) -> float:
    q = x / tick
    return round((math.floor(q + 1e-9) if down else math.ceil(q - 1e-9)) * tick, 10)


def run_session(bars5: list[Bar], day: date, s: dict) -> SessionResult:
    """Walk one session bar by bar. bars5 = 5m bars covering the session AND enough history before it
    (the 15m ADX needs ~30 bars, about 8 hours, so include the day session before)."""
    start, end = session_bounds(day, s)
    res = SessionResult(day.isoformat(), start.isoformat(), end.isoformat())
    ind = s["indicators"]
    bars5 = sorted(bars5, key=lambda b: b.start)
    bb = bollinger([b.c for b in bars5], ind["bb_length"], ind["bb_std"])
    rsi_min, adx_min = ind["rsi_minutes"], ind["adx_minutes"]
    b_rsi, b_adx = resample(bars5, rsi_min), resample(bars5, adx_min)
    v_rsi = rsi([b.c for b in b_rsi], ind["rsi_length"])
    v_adx = adx(b_adx, ind["adx_length"])

    def latest(bars, values, minutes, t_known):
        """The value on the latest COMPLETE bar as of t_known (never one still forming)."""
        span = timedelta(minutes=minutes)
        for i in range(len(bars) - 1, -1, -1):
            if bars[i].start + span <= t_known:
                return values[i]
        return None

    def trend_at(t_known: datetime):
        return latest(b_rsi, v_rsi, rsi_min, t_known), latest(b_adx, v_adx, adx_min, t_known)

    e, c, rules = s["entry"], s["contract"], s["exit"]
    last_entry = datetime.combine(start.date(), dtime.fromisoformat(s["session"]["last_entry"]), tzinfo=start.tzinfo)
    if last_entry < start:
        last_entry += timedelta(days=1)
    # a stop-out costs about 1R (a little under, from whole contracts): two of them end the session
    loss_cap_r = s["account"]["max_session_loss_r"] - 0.1
    idx = [i for i, b in enumerate(bars5) if start <= b.start < end]
    pending = None          # {"side", "i_cross", "waited"}
    trade: Trade | None = None
    realized_r = 0.0

    def t(i):
        return bars5[i].start.astimezone(start.tzinfo).isoformat(timespec="minutes")

    def close_trade(price: float, at: str, why: str):
        nonlocal trade, realized_r
        sign = 1 if trade.side == "long" else -1
        pts = (price - trade.entry) * sign
        cost = trade.contracts * (2 * s["costs"]["commission_per_side"]
                                  + s["costs"]["slippage_ticks"] * c["tick"] * c["point_value"]
                                  * (2 if why in ("stop", "session_end") else 1))
        trade.exit, trade.exit_at, trade.result = round(price, 2), at, why
        trade.pnl_usd = round(pts * c["point_value"] * trade.contracts - cost, 2)
        trade.cost_usd = round(cost, 2)
        risk = abs(trade.entry - trade.stop) * c["point_value"] * trade.contracts
        trade.r = round(trade.pnl_usd / risk, 3) if risk else None
        realized_r += trade.r or 0.0
        res.trades.append(trade)
        trade = None

    for i in idx:
        b = bars5[i]
        # ---- manage an open trade on this bar (levels known before it: the previous bar's middle band)
        if trade is not None:
            mid = bb[i - 1][1] if bb[i - 1] else None
            long = trade.side == "long"
            hit_stop = b.l <= trade.stop if long else b.h >= trade.stop
            if hit_stop:
                gap = b.o < trade.stop if long else b.o > trade.stop
                close_trade(b.o if gap else trade.stop, t(i), "stop")
            else:
                tgt = [(trade.target_2r, "2R")]
                if mid is not None and rules.get("middle_band", True):
                    tgt.append((mid, "middle"))
                tgt.sort(key=lambda x: x[0] if long else -x[0])        # the nearer one first
                for level, why in tgt:
                    if (b.h >= level) if long else (b.l <= level):
                        gap = (b.o > level) if long else (b.o < level)
                        close_trade(b.o if gap else level, t(i), why)
                        break
            if trade is not None and b.start + FIVE >= end:
                close_trade(b.c, t(i), "session_end")
            continue

        if bb[i] is None:
            continue
        lower, mid, upper = bb[i]
        known = b.start + FIVE

        # ---- a pending cross: does this bar's body come back inside?
        if pending is not None:
            side = pending["side"]
            body_hi, body_lo = max(b.o, b.c), min(b.o, b.c)
            back = body_hi > lower if side == "long" else body_lo < upper
            if back:
                pending_i = pending["i_cross"]
                pending = None
                why = None
                if realized_r <= -loss_cap_r:
                    why, res.stopped_for_loss = "session loss limit (2R) reached", True
                elif b.start + FIVE > last_entry:
                    why = "too late in the session"
                if why is None:
                    entry = b.c
                    ext = (min(bars5[pending_i].l, b.l) if side == "long" else max(bars5[pending_i].h, b.h))
                    buf = e["stop_buffer_ticks"] * c["tick"]
                    stop = _round_tick(ext - buf, c["tick"], True) if side == "long" else _round_tick(ext + buf, c["tick"], False)
                    risk = abs(entry - stop)
                    reward_mid = (mid - entry) if side == "long" else (entry - mid)
                    n = contracts_for(risk, s)
                    if risk < e["min_stop_points"]:
                        why = f"stop too tight ({risk:.2f} pts < {e['min_stop_points']})"
                    elif reward_mid < rules["min_reward_r"] * risk:
                        why = f"middle band too close ({reward_mid / risk:.2f}R < {rules['min_reward_r']}R)"
                    elif n < 1:
                        why = f"stop too wide for 1% risk ({risk:.2f} pts)"
                if why is not None:
                    res.skipped.append({"at": t(i), "side": side, "why": why})
                    continue
                r15v, a15v = trend_at(bars5[pending_i].start + FIVE)
                sign = 1 if side == "long" else -1
                trade = Trade(side, t(pending_i), t(i), round(entry, 2), stop,
                              round(entry + sign * rules["target_r"] * risk, 2), round(mid, 2), n,
                              round(r15v, 1), round(a15v, 1))
                if b.start + FIVE >= end:
                    close_trade(b.c, t(i), "session_end")
                continue
            pending["waited"] += 1
            if pending["waited"] >= e["max_wait_bars"]:
                res.skipped.append({"at": t(i), "side": side, "why": "didn't come back inside in time"})
                pending = None
            # (a fresh cross on this bar replaces nothing: one setup at a time)
            continue

        # ---- a new cross?
        side = "long" if b.c < lower else "short" if b.c > upper else None
        if side is None:
            continue
        r15v, a15v = trend_at(known)
        f = s["filters"]
        if r15v is None or a15v is None:
            res.skipped.append({"at": t(i), "side": side, "why": "not enough history for RSI/ADX"})
            continue
        if a15v <= f["adx_min"]:
            res.skipped.append({"at": t(i), "side": side, "why": f"ADX {a15v:.1f} ≤ {f['adx_min']} (choppy)"})
            continue
        if side == "long" and r15v <= f["rsi_long_above"]:
            res.skipped.append({"at": t(i), "side": side, "why": f"RSI {r15v:.1f} not > {f['rsi_long_above']}"})
            continue
        if side == "short" and r15v >= f["rsi_short_below"]:
            res.skipped.append({"at": t(i), "side": side, "why": f"RSI {r15v:.1f} not < {f['rsi_short_below']}"})
            continue
        pending = {"side": side, "i_cross": i, "waited": 0}
    if trade is not None and idx:                 # the data ended before the session did
        close_trade(bars5[idx[-1]].c, t(idx[-1]), "session_end")
    return res
