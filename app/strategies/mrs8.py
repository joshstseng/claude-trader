"""Mr. S, "8 AM retest" (strategy id mrs8): NQ/MNQ, NY AM. Your rules (2026-11-20), all times Pacific:

    reference  the 5:00–5:15 AM 15m candle (8:00 AM ET): its high, low and midpoint
    breakout   from the 6:05 AM 5m bar on (window.breakouts_from), the first 5m candle that CLOSES beyond the
               reference high (long)
               or low (short); only the first breakout counts, one trade a day, no re-entry
    entry      a limit order at the midpoint, in the breakout's direction; cancelled if not filled by 8:00 AM
               (a backtest fill needs price to trade through the midpoint by a tick)
    stop       (long; a short mirrors it) in this order: the most recent 1h swing low below the reference candle
               (stop.swing_tf; "15m" = the nearest 15m swing low, as in runs #27–#30)
               that still holds; if that's too far (> max_stop_atr × the 15m ATR), the nearest holding 15m
               order block, then 15m FVG, then 5m FVG, then 5m order block; worst case the 8:00 candle's
               far side (its low for a long); 2 ticks beyond the level
    target     (target.mode "1h") the nearer of the most recent 1h swing high ≥ 2R away and an unfilled 1h FVG,
               each within 4R; otherwise 2R. ("5m": the most recent 5m lower high 2–3R away, runs #27–#30)
    trend      optional (trend_filter "1h"): the 1h bias from the most recently respected 1h FVG, else the
               last 1h break of structure; breakouts against it are skipped
    exit       stop or target minute by minute (the stop first if one minute touches both); flat at 9:00 AM

Definitions (each counts only once it's confirmed, so a backtest never peeks):
    swing        a fractal: a high (low) above (below) the 2 bars on each side; confirmed when the 2nd bar after closes
    order block  bullish: the last down candle before a candle closing above its high (zone = its low..high);
                 bearish mirrored
    FVG          bullish: bar 1's high < bar 3's low (zone = the gap); bearish mirrored
    holds        no close beyond it since it formed (a swing low / bullish zone: no close below its low)
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from app.strategies.mrs import Bar, contracts_for, resample

PT = ZoneInfo("America/Los_Angeles")
ONE, FIVE, FIFTEEN, HOUR = (timedelta(minutes=m) for m in (1, 5, 15, 60))


# ------------------------------------------------------------------ structure

def swings(bars: list[Bar], span: timedelta, k: int = 2) -> tuple[list, list]:
    """(highs, lows) as (price, formed_at, known_at, index)."""
    highs, lows = [], []
    for j in range(k, len(bars) - k):
        b = bars[j]
        around = bars[j - k:j] + bars[j + 1:j + k + 1]
        known = bars[j + k].start + span
        if all(b.h > x.h for x in around):
            highs.append((b.h, b.start, known, j))
        if all(b.l < x.l for x in around):
            lows.append((b.l, b.start, known, j))
    return highs, lows


def fvgs(bars: list[Bar], span: timedelta) -> list[dict]:
    out = []
    for j in range(2, len(bars)):
        a, c = bars[j - 2], bars[j]
        if a.h < c.l:
            out.append({"kind": "bull", "lo": a.h, "hi": c.l, "known": c.start + span, "j": j})
        elif a.l > c.h:
            out.append({"kind": "bear", "lo": c.h, "hi": a.l, "known": c.start + span, "j": j})
    return out


def order_blocks(bars: list[Bar], span: timedelta, look: int = 3) -> list[dict]:
    out = []
    for j in range(len(bars) - 1):
        b = bars[j]
        for x in bars[j + 1:j + 1 + look]:
            if b.c < b.o and x.c > b.h:
                out.append({"kind": "bull", "lo": b.l, "hi": b.h, "known": x.start + span, "j": j})
                break
            if b.c > b.o and x.c < b.l:
                out.append({"kind": "bear", "lo": b.l, "hi": b.h, "known": x.start + span, "j": j})
                break
    return out


def _holds(bars: list[Bar], j: int, level: float, long: bool, span: timedelta, t: datetime) -> bool:
    """No bar after j (finished by t) closed beyond the level."""
    for x in bars[j + 1:]:
        if x.start + span > t:
            break
        if (x.c < level) if long else (x.c > level):
            return False
    return True


def atr(bars: list[Bar], span: timedelta, t: datetime, n: int = 14) -> float | None:
    done = [b for b in bars if b.start + span <= t][-(n + 1):]
    if len(done) < n + 1:
        return None
    trs = [max(b.h - b.l, abs(b.h - p.c), abs(b.l - p.c)) for p, b in zip(done, done[1:])]
    return sum(trs) / len(trs)


# ------------------------------------------------------------------ the pieces

def bias_1h(h1: list[Bar], t: datetime) -> tuple[str | None, str]:
    """('bull'/'bear'/None, why) as of t: the most recent 1h FVG price came back into and respected (no 1h
    close through its far side); else the last 1h break of structure (a close beyond the latest swing)."""
    done = [b for b in h1 if b.start + HOUR <= t]
    best = None                                      # (time it was respected, kind)
    for g in fvgs(done, HOUR):
        long = g["kind"] == "bull"
        for x in done[g["j"] + 1:]:
            if (x.c < g["lo"]) if long else (x.c > g["hi"]):
                break                                # closed through: not respected
            if (x.l <= g["hi"]) if long else (x.h >= g["lo"]):
                if best is None or x.start > best[0]:
                    best = (x.start, g["kind"])
                break                                # tested and held
    if best is not None:
        return best[1], "1h FVG respected"
    highs, lows = swings(done, HOUR)
    last = None
    for x in done:
        hs = [h for h in highs if h[2] <= x.start]
        ls = [l_ for l_ in lows if l_[2] <= x.start]
        if hs and x.c > hs[-1][0]:
            last = "bull"
        elif ls and x.c < ls[-1][0]:
            last = "bear"
    return last, "1h break of structure" if last else "no 1h structure"


def find_stop(long: bool, entry: float, ref_lo: float, ref_hi: float, b15: list[Bar], b5: list[Bar],
              t: datetime, s: dict, h1: list[Bar] | None = None) -> tuple[float | None, str]:
    """(stop level before the buffer, where it came from) or (None, why not)."""
    st = s["stop"]
    a = atr(b15, FIFTEEN, t)
    if a is None:
        return None, "not enough 15m history"
    far = st["max_stop_atr"] * a
    ok = lambda lvl: st["min_stop_points"] <= ((entry - lvl) if long else (lvl - entry)) <= far   # noqa: E731

    # 1. a holding swing low below the reference candle (high above, for a short):
    #    stop.swing_tf "1h": the MOST RECENT 1h one (2026-11-20); "15m": the nearest 15m one (runs #27–#30)
    tf_1h = st.get("swing_tf", "15m") == "1h" and h1 is not None
    sb, span, name = (h1, HOUR, "1h") if tf_1h else (b15, FIFTEEN, "15m")
    highs, lows = swings(sb, span)
    pts = [p for p in (lows if long else highs) if p[2] <= t and ((p[0] < ref_lo) if long else (p[0] > ref_hi))
           and _holds(sb, p[3], p[0], long, span, t)]
    if pts:
        if tf_1h:
            level = max(pts, key=lambda p: p[1])[0]                       # the most recent
        else:
            level = max(p[0] for p in pts) if long else min(p[0] for p in pts)
        if ok(level):
            return level, f"{name} swing {'low' if long else 'high'}"

    def zone(cands, bars, span, name):
        kind = "bull" if long else "bear"
        zs = [z for z in cands if z["kind"] == kind and z["known"] <= t
              and ((z["hi"] < entry) if long else (z["lo"] > entry))
              and _holds(bars, z["j"], z["lo"] if long else z["hi"], long, span, t)]
        lv = [z["lo"] if long else z["hi"] for z in zs]
        lv = [x for x in lv if ok(x)]
        if lv:
            return (max(lv) if long else min(lv)), name
        return None

    for got in (lambda: zone(order_blocks(b15, FIFTEEN), b15, FIFTEEN, "15m order block"),
                lambda: zone(fvgs(b15, FIFTEEN), b15, FIFTEEN, "15m FVG"),
                lambda: zone(fvgs(b5, FIVE), b5, FIVE, "5m FVG"),
                lambda: zone(order_blocks(b5, FIVE), b5, FIVE, "5m order block")):
        r = got()
        if r:
            return r
    # worst case (your rule, 2026-11-20): the far side of the 8:00 ET candle itself
    level = ref_lo if long else ref_hi
    if ((entry - level) if long else (level - entry)) >= st["min_stop_points"]:
        return level, "8:00 candle"
    return None, "no swing, order block or FVG, and the 8:00 candle is too small"


def find_target_1h(long: bool, entry: float, risk: float, h1: list[Bar], t: datetime, s: dict) -> tuple[float, str]:
    """target.mode "1h" (2026-11-20): the nearer of (a) the most recent 1h swing high (low, for a short) at least
    level_min_r away and (b) an unfilled 1h FVG beyond the entry (its near edge), each within level_max_r;
    otherwise default_r."""
    tg = s["target"]
    sign = 1 if long else -1
    lo_r, hi_r = tg["level_min_r"], tg["level_max_r"]
    in_r = lambda x: lo_r <= (x - entry) * sign / risk <= hi_r                    # noqa: E731
    done = [b for b in h1 if b.start + HOUR <= t]
    cands = []
    highs, lows = swings(done, HOUR)
    for p in reversed(highs if long else lows):                                # the most recent first
        if (p[0] - entry) * sign / risk >= lo_r:
            if in_r(p[0]):
                cands.append((p[0], "1h swing " + ("high" if long else "low")))
            break
    for g in fvgs(done, HOUR):
        near = g["lo"] if long else g["hi"]
        far = g["hi"] if long else g["lo"]
        if (near - entry) * sign <= 0:
            continue
        filled = any((x.h >= far) if long else (x.l <= far) for x in done[g["j"] + 1:])
        if not filled and in_r(near):
            cands.append((near, "1h FVG"))
    if cands:
        price, src = min(cands, key=lambda c: abs(c[0] - entry))
        return price, f"{src} ({(price - entry) * sign / risk:.1f}R)"
    return entry + sign * tg["default_r"] * risk, f"{tg['default_r']:g}R"


def find_target(long: bool, entry: float, risk: float, b5: list[Bar], t: datetime, s: dict) -> tuple[float, str]:
    """The most recent 5m lower high (long) / higher low (short) 2–3R away, else 2R (runs #27–#30)."""
    tg = s["target"]
    highs, lows = swings(b5, FIVE)
    pts = [p for p in (highs if long else lows) if p[2] <= t]
    lh = None
    for prev, cur in zip(pts, pts[1:]):
        if (cur[0] < prev[0]) if long else (cur[0] > prev[0]):
            if (cur[0] > entry) if long else (cur[0] < entry):
                lh = cur
    sign = 1 if long else -1
    if lh is not None:
        r = (lh[0] - entry) * sign / risk
        if tg["level_min_r"] <= r <= tg["level_max_r"]:
            return lh[0], f"5m {'lower high' if long else 'higher low'} ({r:.1f}R)"
    return entry + sign * tg["default_r"] * risk, f"{tg['default_r']:g}R"


# ------------------------------------------------------------------ one day

@dataclass
class Trade8:
    day: str
    side: str
    ref_hi: float
    ref_lo: float
    break_at: str
    entry_at: str
    entry: float
    stop: float
    stop_from: str
    target: float
    target_from: str
    contracts: int
    bias: str | None
    exit_at: str | None = None
    exit: float | None = None
    result: str | None = None        # target / stop / session_end
    r: float | None = None
    pnl_usd: float | None = None
    cost_usd: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Day8:
    day: str
    trade: Trade8 | None = None
    why: str | None = None           # no trade: the reason

    @property
    def trades(self):
        return [self.trade] if self.trade else []


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, dtime.fromisoformat(hhmm), tzinfo=PT)


def _tick(x: float, tick: float, down: bool) -> float:
    q = x / tick
    return round((math.floor(q + 1e-9) if down else math.ceil(q - 1e-9)) * tick, 10)


def run_day(bars1: list[Bar], day: date, s: dict) -> Day8:
    """bars1: 1m bars from a few days before (for 15m/1h structure) through the session."""
    out = Day8(day.isoformat())
    w = s["window"]
    ref_t, look_t, expire_t, flat_t = (_at(day, w[k]) for k in ("reference", "breakouts_from", "order_until", "flat"))
    bars1 = [b for b in bars1 if b.start < flat_t]
    from app.backtest.dukascopy import to_5m
    b5 = to_5m([[int(b.start.timestamp()), b.o, b.h, b.l, b.c] for b in bars1])
    b15, h1 = resample(b5, 15), resample(b5, 60)
    ref = next((b for b in b15 if b.start == ref_t), None)
    if ref is None:
        out.why = "no 8:00 ET candle (market closed?)"
        return out
    mid = (ref.h + ref.l) / 2
    c = s["contract"]

    # ---- the breakout
    brk = next((b for b in b5 if look_t <= b.start and b.start + FIVE <= expire_t
                and (b.c > ref.h or b.c < ref.l)), None)
    if brk is None:
        out.why = "no breakout by 8:00"
        return out
    long = brk.c > ref.h
    side = "long" if long else "short"
    placed = brk.start + FIVE
    bias = None
    if s.get("trend_filter") == "1h":
        bias, _ = bias_1h(h1, placed)
        if bias != ("bull" if long else "bear"):
            out.why = f"against the 1h trend ({bias or 'none'})"
            return out

    # ---- stop and target (known when the order goes in)
    entry = _tick(mid, c["tick"], not long)                  # a long buys at or below the midpoint
    level, src = find_stop(long, entry, ref.l, ref.h, b15, b5, placed, s, h1=h1)
    if level is None:
        out.why = src
        return out
    buf = s["stop"]["buffer_ticks"] * c["tick"]
    stop = _tick(level - buf, c["tick"], True) if long else _tick(level + buf, c["tick"], False)
    risk = abs(entry - stop)
    n = contracts_for(risk, s)
    if n < 1:
        out.why = f"stop too wide for 1% ({risk:.1f} pts)"
        return out
    if s["target"].get("mode", "5m") == "1h":
        target, tsrc = find_target_1h(long, entry, risk, h1, placed, s)
    else:
        target, tsrc = find_target(long, entry, risk, b5, placed, s)
    target = round(target, 2)

    # ---- fill (trade-through by a tick), then manage minute by minute
    i = bisect_left([b.start for b in bars1], placed)
    fill_i = None
    for j in range(i, len(bars1)):
        b = bars1[j]
        if b.start >= expire_t:
            break
        if (b.l <= entry - c["tick"]) if long else (b.h >= entry + c["tick"]):
            fill_i = j
            break
    if fill_i is None:
        out.why = "limit not filled by 8:00"
        return out
    fb = bars1[fill_i]
    fill = min(entry, fb.o) if long else max(entry, fb.o)      # opened through the level: filled at the open
    tr = Trade8(day.isoformat(), side, ref.h, ref.l, brk.start.astimezone(PT).isoformat(timespec="minutes"),
                fb.start.astimezone(PT).isoformat(timespec="minutes"), round(fill, 2), stop, src, target, tsrc,
                n, bias)
    for j in range(fill_i, len(bars1)):
        b = bars1[j]
        at = b.start.astimezone(PT).isoformat(timespec="minutes")
        if (b.l <= stop) if long else (b.h >= stop):
            gap = (b.o < stop) if long else (b.o > stop)
            _close(tr, b.o if gap and j > fill_i else stop, at, "stop", s)
            break
        if j > fill_i and ((b.h >= target) if long else (b.l <= target)):
            gap = (b.o > target) if long else (b.o < target)
            _close(tr, b.o if gap else target, at, "target", s)
            break
        if b.start + ONE >= flat_t or j == len(bars1) - 1:
            _close(tr, b.c, at, "session_end", s)
            break
    out.trade = tr
    return out


def _close(tr: Trade8, price: float, at: str, why: str, s: dict) -> None:
    c, k = s["contract"], s["costs"]
    sign = 1 if tr.side == "long" else -1
    slip = k["slippage_ticks"] * c["tick"] * c["point_value"] if why in ("stop", "session_end") else 0.0
    cost = tr.contracts * (2 * k["commission_per_side"] + slip)            # a limit entry: no slippage
    tr.exit, tr.exit_at, tr.result = round(price, 2), at, why
    tr.cost_usd = round(cost, 2)
    tr.pnl_usd = round((price - tr.entry) * sign * c["point_value"] * tr.contracts - cost, 2)
    risk = abs(tr.entry - tr.stop) * c["point_value"] * tr.contracts
    tr.r = round(tr.pnl_usd / risk, 3) if risk else None
