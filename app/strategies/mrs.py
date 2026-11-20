"""Mr. S: Bollinger mean-reversion on NQ futures (MNQ), Asia session first. Plan: plans/mrs-strategy.md

Version A, "trend pullback" (the default settings):
    1h   RSI(14) > 55 -> longs only, < 45 -> shorts only (indicators.rsi_minutes)
    15m  ADX(14) > 20 (trending) (indicators.adx_minutes)
    5m   a bar CLOSES outside the Bollinger Band (20, 2): below the lower band for a long, above the upper for a short
    5m   within the next 2 bars, the first bar with any part of its BODY back inside the band -> enter at its close
    stop the extreme of the cross bar and the entry bar (lowest low for a long), plus a small buffer
    exit the middle band (moves each bar) or 2R, whichever comes first; the stop first if a bar hits both;
         everything flat at the session end
    risk 1% of the account per trade (whole contracts); the session stops at -2R or +3R net; one trade at a time

AMD gate (accumulation.enabled): setups only count while the market is in accumulation (a tight 60-min
box, see accumulation()); a breakout out of the box (manipulation) stops it until a new box forms.

Version B, "range fade": filters.adx_min=-1, filters.adx_max=20, filters.use_rsi=false: only when ADX is
under 20 (a range), fading either band, no RSI direction.

Everything here is pure: bars in, setups and trades out. The live bot (Discord, Tradovate) and the backtest
scenarios come later. Times: bars are tagged by their START; a 5m bar's values are known at start + 5 min.
NQ and MNQ trade at the same price, so NQ bars test MNQ (only the dollars per point differ).
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
FIVE = timedelta(minutes=5)
ONE = timedelta(minutes=1)


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
    result: str | None = None     # middle / 2R / stop / be_stop / lock_stop / session_end
    r: float | None = None        # after costs
    pnl_usd: float | None = None  # after costs
    cost_usd: float | None = None
    stop_now: float | None = None # the stop after any moves (break-even, +1R); None = never moved

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
    stopped_for_win: bool = False

    @property
    def pnl_usd(self) -> float:
        return round(sum(t.pnl_usd or 0 for t in self.trades), 2)


def accumulation(bars5: list[Bar], a: dict) -> list[dict | None] | None:
    """AMD's accumulation phase, bar by bar (None when accumulation.enabled is off).

    For bar i, from the bars BEFORE it: the box = the high and low of the last lookback_minutes (60), all
    back-to-back 5m bars; ATR = the average true range of the 14 bars before i. Accumulation ("box") is on
    when the box is no taller than max_height_atr × ATR (3×: normal movement over an hour is ~4–5×) and no
    breakout happened inside the window. A bar closing more than breakout_atr × ATR (1×) outside the box
    is a breakout ("broke_out": manipulation has started); a new box then has to form from the bars after it.
    """
    if not a.get("enabled"):
        return None
    n = a["lookback_minutes"] // 5
    k, m, bo = a["max_height_atr"], a["atr_length"], a["breakout_atr"]
    tr = [b.h - b.l if j == 0 else max(b.h - b.l, abs(b.h - bars5[j - 1].c), abs(b.l - bars5[j - 1].c))
          for j, b in enumerate(bars5)]
    out: list[dict | None] = [None] * len(bars5)
    last_bo = -1
    span = (n - 1) * FIVE
    for j in range(max(n, m), len(bars5)):
        w = bars5[j - n:j]
        if w[-1].start - w[0].start != span or bars5[j].start - w[-1].start != FIVE:
            continue                                      # a gap (the daily halt, missing data): no box
        atr_v = sum(tr[j - m:j]) / m
        hi, lo = max(b.h for b in w), min(b.l for b in w)
        box = j - n > last_bo and atr_v > 0 and (hi - lo) <= k * atr_v
        c = bars5[j].c
        broke = box and (c > hi + bo * atr_v or c < lo - bo * atr_v)
        if broke:
            last_bo = j
        out[j] = {"box": box, "hi": hi, "lo": lo, "atr": atr_v, "broke_out": broke}
    return out


def _round_tick(x: float, tick: float, down: bool) -> float:
    q = x / tick
    return round((math.floor(q + 1e-9) if down else math.ceil(q - 1e-9)) * tick, 10)


def run_session(bars5: list[Bar], day: date, s: dict, bars1: list[Bar] | None = None) -> SessionResult:
    """Walk one session bar by bar. bars5 = 5m bars covering the session AND enough history before it
    (RSI and ADX need several hours, so include the day session before).
    entry.timeframe "1m" (needs bars1, the session's 1-minute bars): after the 5m setup, enter on the first
    1m candle closing back toward the middle (bullish for a long, bearish for a short) with any part of its
    body inside the band, within entry.max_wait_minutes; the trade is then managed minute by minute."""
    start, end = session_bounds(day, s)
    res = SessionResult(day.isoformat(), start.isoformat(), end.isoformat())
    ind = s["indicators"]
    bars5 = sorted(bars5, key=lambda b: b.start)
    bb = bollinger([b.c for b in bars5], ind["bb_length"], ind["bb_std"])
    rsi_min, adx_min = ind["rsi_minutes"], ind["adx_minutes"]
    b_rsi, b_adx = resample(bars5, rsi_min), resample(bars5, adx_min)
    v_rsi = rsi([b.c for b in b_rsi], ind["rsi_length"])
    v_adx = adx(b_adx, ind["adx_length"])
    accum = accumulation(bars5, s.get("accumulation") or {})

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
                                  * (2 if why in ("stop", "be_stop", "lock_stop", "session_end") else 1))
        trade.exit, trade.exit_at, trade.result = round(price, 2), at, why
        trade.pnl_usd = round(pts * c["point_value"] * trade.contracts - cost, 2)
        trade.cost_usd = round(cost, 2)
        risk = abs(trade.entry - trade.stop) * c["point_value"] * trade.contracts
        trade.r = round(trade.pnl_usd / risk, 3) if risk else None
        realized_r += trade.r or 0.0
        res.trades.append(trade)
        trade = None

    move = {"why": "stop", "peak": None, "prev_h": None}   # this trade's stop moves (exit.breakeven_at_r...)

    def step_stop(b: Bar) -> None:
        """After a bar closes: +1R reached -> stop to break-even (exit.breakeven_at_r); an internal high beyond
        exit.lock_r (a bar's extreme past that level, confirmed by the next bar not going further) -> stop to
        +lock_r. Stops only ever move toward profit."""
        be_at, lock_r = rules.get("breakeven_at_r"), rules.get("lock_r")
        if be_at is None and lock_r is None:
            return
        sign = 1 if trade.side == "long" else -1
        risk = abs(trade.entry - trade.stop)
        ext = b.h if sign > 0 else b.l
        best = (ext - trade.entry) * sign / risk                       # this bar's best, in R
        cur = trade.stop_now if trade.stop_now is not None else trade.stop

        def to(level: float, why: str):
            if (level - cur) * sign > 0:
                trade.stop_now, move["why"] = round(level, 2), why
        if be_at is not None and best >= be_at:
            to(trade.entry, "be_stop")
        prev = move["prev_h"]
        if lock_r is not None and prev is not None:
            prev_best = (prev - trade.entry) * sign / risk
            if prev_best > lock_r and (ext - prev) * sign <= 0:        # this bar didn't beat it: an internal high
                to(trade.entry + sign * lock_r * risk, "lock_stop")
        move["prev_h"] = ext

    def manage(b: Bar, mid: float | None, at: str, span: timedelta) -> None:
        """One bar of an open trade: the stop first (if a bar touches both), then the nearer of 2R and the
        middle band (levels known before the bar), the session end, then move the stop for the next bar."""
        long = trade.side == "long"
        stop = trade.stop_now if trade.stop_now is not None else trade.stop
        if b.l <= stop if long else b.h >= stop:
            gap = b.o < stop if long else b.o > stop
            close_trade(b.o if gap else stop, at, move["why"])
        else:
            tgt = [(trade.target_2r, "2R")]
            if mid is not None and rules.get("middle_band", True):
                tgt.append((mid, "middle"))
            tgt.sort(key=lambda x: x[0] if long else -x[0])            # the nearer one first
            for level, why in tgt:
                if (b.h >= level) if long else (b.l <= level):
                    gap = (b.o > level) if long else (b.o < level)
                    close_trade(b.o if gap else level, at, why)
                    break
        if trade is not None and b.start + span >= end:
            close_trade(b.c, at, "session_end")
        if trade is not None:
            step_stop(b)                       # at this bar's close: move the stop for the next bar

    def refuse(side: str, entry: float, ext: float, mid: float, entry_end: datetime):
        """-> (why or None, stop, risk, contracts): the session limits, the clock, and the stop/reward checks."""
        win_cap = s["account"].get("max_session_win_r")
        if realized_r <= -loss_cap_r:
            res.stopped_for_loss = True
            return "session loss limit (2R) reached", None, None, None
        if win_cap is not None and realized_r >= win_cap:
            res.stopped_for_win = True
            return f"session win limit ({win_cap:g}R) reached", None, None, None
        if entry_end > last_entry:
            return "too late in the session", None, None, None
        buf = e["stop_buffer_ticks"] * c["tick"]
        stop = _round_tick(ext - buf, c["tick"], True) if side == "long" else _round_tick(ext + buf, c["tick"], False)
        risk = abs(entry - stop)
        reward_mid = (mid - entry) if side == "long" else (entry - mid)
        n = contracts_for(risk, s)
        if risk < e["min_stop_points"]:
            return f"stop too tight ({risk:.2f} pts < {e['min_stop_points']})", stop, risk, n
        if reward_mid < rules["min_reward_r"] * risk:
            return f"middle band too close ({reward_mid / risk:.2f}R < {rules['min_reward_r']}R)", stop, risk, n
        if n < 1:
            return f"stop too wide for 1% risk ({risk:.2f} pts)", stop, risk, n
        return None, stop, risk, n

    def open_trade(side, cross_at, entry_at, entry, stop, risk, mid, n, cross_known):
        nonlocal trade
        r_v, a_v = trend_at(cross_known)
        sign = 1 if side == "long" else -1
        move.update(why="stop", prev_h=None)
        trade = Trade(side, cross_at, entry_at, round(entry, 2), stop,
                      round(entry + sign * rules["target_r"] * risk, 2), round(mid, 2), n,
                      round(r_v, 1), round(a_v, 1))

    # ---- the 1m entry: find the candle, then manage minute by minute
    use_1m = e.get("timeframe", "5m") == "1m"
    if use_1m:
        if bars1 is None:
            raise ValueError("entry.timeframe 1m needs the 1-minute bars")
        bars1 = sorted(bars1, key=lambda b: b.start)
        t1 = [b.start for b in bars1]
        ends5 = [b.start + FIVE for b in bars5]

    def band_at(when: datetime):
        """The Bollinger Band of the latest 5m bar finished by `when`."""
        k = bisect_right(ends5, when) - 1
        return bb[k] if k >= 0 else None

    def tm(when: datetime) -> str:
        return when.astimezone(start.tzinfo).isoformat(timespec="minutes")

    def take_1m(i_cross: int, side: str) -> datetime:
        """Search the 1m chart after the 5m setup; trade it if it qualifies. Returns when the 5m scan resumes."""
        long = side == "long"
        known = bars5[i_cross].start + FIVE
        wait_end = known + timedelta(minutes=e.get("max_wait_minutes", 10))
        ext = bars5[i_cross].l if long else bars5[i_cross].h
        j = bisect_left(t1, known)
        while j < len(bars1) and bars1[j].start < min(wait_end, end):
            m = bars1[j]
            ext = min(ext, m.l) if long else max(ext, m.h)
            band = band_at(m.start + ONE)
            if band is not None:
                lower, mid, upper = band
                ok = (m.c > m.o and m.c > lower) if long else (m.c < m.o and m.c < upper)   # body inside
                if ok:
                    why, stop, risk, n = refuse(side, m.c, ext, mid, m.start + ONE)
                    if why is not None:
                        res.skipped.append({"at": tm(m.start), "side": side, "why": why})
                        return m.start + ONE
                    open_trade(side, t(i_cross), tm(m.start), m.c, stop, risk, mid, n, known)
                    k = j + 1
                    while trade is not None and k < len(bars1) and bars1[k].start < end:
                        x = bars1[k]
                        b5 = band_at(x.start)
                        manage(x, b5[1] if b5 else None, tm(x.start), ONE)
                        k += 1
                    if trade is not None:                             # the data ended before the session
                        last = bars1[min(k, len(bars1)) - 1]
                        close_trade(last.c, tm(last.start), "session_end")
                    return datetime.fromisoformat(res.trades[-1].exit_at) + ONE
            j += 1
        res.skipped.append({"at": tm(min(wait_end, end)), "side": side, "why": "didn't come back inside in time"})
        return wait_end

    resume_at = None                            # 1m mode: the 5m scan waits while a setup or trade plays out
    for i in idx:
        b = bars5[i]
        if resume_at is not None and b.start + FIVE <= resume_at:
            continue
        # ---- manage an open trade on this bar (levels known before it: the previous bar's middle band)
        if trade is not None:
            manage(b, bb[i - 1][1] if bb[i - 1] else None, t(i), FIVE)
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
                ext = (min(bars5[pending_i].l, b.l) if side == "long" else max(bars5[pending_i].h, b.h))
                why, stop, risk, n = refuse(side, b.c, ext, mid, b.start + FIVE)
                if why is not None:
                    res.skipped.append({"at": t(i), "side": side, "why": why})
                    continue
                open_trade(side, t(pending_i), t(i), b.c, stop, risk, mid, n, bars5[pending_i].start + FIVE)
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
        if accum is not None:                                            # AMD: only inside accumulation
            st = accum[i]
            if st is None or not st["box"]:
                res.skipped.append({"at": t(i), "side": side, "why": "not in accumulation"})
                continue
            if st["broke_out"]:
                res.skipped.append({"at": t(i), "side": side, "why": "range broke out (manipulation)"})
                continue
        r15v, a15v = trend_at(known)
        f = s["filters"]
        if r15v is None or a15v is None:
            res.skipped.append({"at": t(i), "side": side, "why": "not enough history for RSI/ADX"})
            continue
        if a15v <= f["adx_min"]:
            res.skipped.append({"at": t(i), "side": side, "why": f"ADX {a15v:.1f} ≤ {f['adx_min']} (choppy)"})
            continue
        if f.get("adx_max") is not None and a15v >= f["adx_max"]:      # version B: only in a range
            res.skipped.append({"at": t(i), "side": side, "why": f"ADX {a15v:.1f} ≥ {f['adx_max']} (trending)"})
            continue
        if not f.get("use_rsi", True):
            pass                                                         # version B: fade either band
        elif side == "long" and r15v <= f["rsi_long_above"]:
            res.skipped.append({"at": t(i), "side": side, "why": f"RSI {r15v:.1f} not > {f['rsi_long_above']}"})
            continue
        elif side == "short" and r15v >= f["rsi_short_below"]:
            res.skipped.append({"at": t(i), "side": side, "why": f"RSI {r15v:.1f} not < {f['rsi_short_below']}"})
            continue
        if use_1m:
            resume_at = take_1m(i, side)
            continue
        pending = {"side": side, "i_cross": i, "waited": 0}
    if trade is not None and idx:                 # the data ended before the session did
        close_trade(bars5[idx[-1]].c, t(idx[-1]), "session_end")
    return res
