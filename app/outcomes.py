"""What a trade plan actually did: target first, stop first, or flat at the flat-by time.

Shared by the live bot (after the close, Step 1a.7) and the backtest (Step 2), so both count
results exactly the same way.

Rules (long only, 5-minute bars):
- The trade starts at the entry price when the trigger bar closes. Bars from then on are walked
  in order, up to the flat-by time (3:55 PM, or 12:55 PM on an early close).
- Stop: a bar's low at or below the stop. If the bar OPENED below the stop (a gap), the exit is
  that open, not the stop: a stop order fills at the next price, which can be worse.
- Target: a bar's high at or above the target; the exit is the target price (a limit order).
- Both in the same bar: counted as a STOP. Inside one 5-minute bar we can't tell which came
  first, so we assume the worse one.
- Neither by the flat-by time: "flat", exit at the price at the flat-by time (the close of the
  bar that ends then).
- Costs: `cost_pct` of the price per side (entry and exit), for spread + slippage.

Also returns how far the trade went in your favor (MFE) and against you (MAE) in R, which lets
the backtest see what a different target would have done without re-walking bars.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
BAR = timedelta(minutes=5)
METHOD = "5m bars; stop first if both in one bar; gaps fill at the open"


@dataclass(frozen=True)
class Bar:
    start: datetime   # New York time
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass(frozen=True)
class Outcome:
    result: str                 # target / stop / flat / no_data
    exit_price: float | None
    exit_time: str | None       # "HH:MM" New York
    r_gross: float | None       # before costs
    r_net: float | None         # after costs  <- the number that counts
    pnl_usd: float | None       # after costs, for `qty` shares
    cost_usd: float | None
    mfe_r: float | None         # best move in your favor before the exit, in R
    mae_r: float | None         # worst move against you before the exit, in R
    bars_held: int
    method: str = METHOD

    def as_dict(self) -> dict:
        return asdict(self)


def resolve(*, entry: float, stop: float, target: float, entry_at: datetime, bars: list[Bar],
            flat_by: dtime = dtime(15, 55), qty: int | None = None, cost_pct: float = 0.0) -> Outcome:
    """Walk the bars after the entry and say how the trade ended."""
    if not (stop < entry < target):
        raise ValueError(f"long plan needs stop < entry < target, got {stop} / {entry} / {target}")
    risk = entry - stop
    flat_at = datetime.combine(entry_at.date(), flat_by, tzinfo=NY)
    after = sorted((b for b in bars if b.start >= entry_at and b.start + BAR <= flat_at),
                   key=lambda b: b.start)
    if not after:
        return Outcome("no_data", None, None, None, None, None, None, None, None, 0)

    best, worst = entry, entry
    result, exit_price, exit_at, held = "flat", after[-1].c, after[-1].start + BAR, len(after)
    for i, b in enumerate(after, start=1):
        hit_stop, hit_target = b.l <= stop, b.h >= target
        if hit_stop:                                  # also wins a tie with the target
            result, exit_price, exit_at, held = "stop", min(stop, b.o), b.start + BAR, i
            worst = min(worst, exit_price)
            break
        worst = min(worst, b.l)
        if hit_target:                                # the trade is out at the target: nothing beyond it counts
            result, exit_price, exit_at, held = "target", target, b.start + BAR, i
            best = max(best, target)
            break
        best = max(best, b.h)

    cost_per_share = cost_pct * (entry + exit_price)
    gross = exit_price - entry
    net = gross - cost_per_share
    return Outcome(
        result=result,
        exit_price=round(exit_price, 4),
        exit_time=exit_at.strftime("%H:%M"),
        r_gross=round(gross / risk, 3),
        r_net=round(net / risk, 3),
        pnl_usd=round(net * qty, 2) if qty else None,
        cost_usd=round(cost_per_share * qty, 2) if qty else None,
        mfe_r=round((best - entry) / risk, 3),
        mae_r=round((worst - entry) / risk, 3),
        bars_held=held,
    )


# ------------------------------------------------------------------ bar sources

def bars_from_rows(rows: list[dict]) -> list[Bar]:
    """[{"t": "YYYY-MM-DD HH:MM" (New York), "o", "h", "l", "c", "v"}] -> bars."""
    return [Bar(datetime.strptime(r["t"], "%Y-%m-%d %H:%M").replace(tzinfo=NY),
                float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]), float(r.get("v") or 0))
            for r in rows]


def bars_from_alpaca(bars) -> list[Bar]:
    """alpaca-py Bar objects -> bars."""
    return [Bar(b.timestamp.astimezone(NY), float(b.open), float(b.high), float(b.low),
                float(b.close), float(b.volume or 0)) for b in bars]


def bars_from_yahoo(chart: dict) -> list[Bar]:
    """A Yahoo v8 chart JSON -> bars (rows with a missing price are skipped)."""
    res = chart["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        out.append(Bar(datetime.fromtimestamp(ts, NY), *map(float, vals), float(q["volume"][i] or 0)))
    return out


def entry_datetime(date: str, entry_time: str) -> datetime:
    """('2026-10-19', '10:15 AM' or '10:15') -> when the trigger bar closed, New York."""
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            t = datetime.strptime(entry_time.strip(), fmt).time()
            return datetime.combine(datetime.strptime(date, "%Y-%m-%d").date(), t, tzinfo=NY)
        except ValueError:
            continue
    raise ValueError(f"can't read entry time {entry_time!r}")
