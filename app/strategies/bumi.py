"""Bumi (strategy id bumi): buys fearful dips in the big index ETFs through their 2x funds, and holds QQQ in calm
markets. Daily bars; every decision is made after the close and traded at the next open. Runs through app/bumi_run.py,
not app.strategies.BRAINS, because it holds for days (plans/bumi-setup.md).

    dip entry  VIX above 20, the ETF above its 200-day average, and 2-day RSI under 10 or IBS under 0.1
    dip trade  25% of the account in the ETF's 2x fund (QLD, SSO, UWM, DDM)
    dip exit   a stop 3 ATR under the first open, trailing 1.5 ATR under the best high. It is CHECKED on each day's
               low after the close and SOLD at the next open. A resting stop tested far worse.
    core       50% of the account in QQQ while SPY is above its 200-day average and VIX is under 20. Dip trades have
               first call on cash, so the account never borrows to hold the core
    idle cash  T-bills in the research; plain cash on paper
"""

from __future__ import annotations

from dataclasses import dataclass

from app.research.daily import atr, rsi, sma


@dataclass
class Track:
    """One ETF's dip-trade state at each close."""
    want: list[bool]              # hold the 2x fund after the next open
    stop: list[float | None]      # the stop after this close (None when flat or newly signaled)
    since: list[int | None]       # the signal bar of the trade being held
    why: list[str | None]         # why a trade was signaled on this bar


def _signal(bars, i, vix, s, c, trend, r) -> str | None:
    e = s["entry"]
    if trend[i] is None or r[i] is None or not vix[i] > e["vix_above"] or not c[i] > trend[i]:
        return None
    b = bars[i]
    ib = (b.c - b.l) / (b.h - b.l) if b.h > b.l else 0.5
    if r[i] < e["rsi_below"]:
        return f"RSI(2) {r[i]:.1f}, VIX {vix[i]:.1f}"
    if ib < e["ibs_below"]:
        return f"IBS {ib:.2f}, VIX {vix[i]:.1f}"
    return None


def track(bars: list, vix: list[float], s: dict) -> Track:
    """Replay the dip rules through the last bar, so the last entry is tomorrow's decision."""
    n = len(bars)
    if len(vix) != n:
        raise ValueError("VIX and bars must be aligned")
    e, st = s["entry"], s["stop"]
    c = [b.c for b in bars]
    trend, r, a = sma(c, e["trend_sma"]), rsi(c, e["rsi_period"]), atr(bars, st["atr_period"])
    out = Track([False] * n, [None] * n, [None] * n, [None] * n)
    i = 0
    while i < n:
        why = _signal(bars, i, vix, s, c, trend, r) if a[i] is not None else None
        if why is None:
            i += 1
            continue
        out.want[i], out.since[i], out.why[i] = True, i, why
        j = i + 1
        if j >= n:
            break
        stop = bars[j].o - st["start_atr"] * a[i]
        best = bars[j].o
        while j < n:
            if bars[j].l <= stop:
                break
            best = max(best, bars[j].h)
            stop = max(stop, best - st["trail_atr"] * a[j])
            if j - i >= st["max_days"]:
                break
            out.want[j], out.stop[j], out.since[j] = True, stop, i
            j += 1
        if j >= n:
            break
        i = j
    return out


def calm(spy_bars: list, vix: list[float], s: dict) -> list[bool]:
    co = s["core"]
    c = [b.c for b in spy_bars]
    m = sma(c, co["trend_sma"])
    return [m[k] is not None and c[k] > m[k] and vix[k] < co["vix_below"] for k in range(len(c))]


def weights(dips_on: dict[str, bool], is_calm: bool, s: dict) -> dict[str, float]:
    """Target weights of the account after the next open (anything left over is cash)."""
    x = {s["universe"][u]: s["sizing"]["dip_weight"] for u, on in dips_on.items() if on}
    if is_calm:
        f = min(s["core"]["weight"], max(0.0, 1.0 - sum(x.values())))
        if f > 0:
            x[s["core"]["symbol"]] = f
    return x


def plan_next(bars_by_sym: dict[str, list], vix: list[float], s: dict, vix_fresh: bool = True) -> dict:
    """What Bumi does at the next open, from final, date-aligned daily bars. Places nothing.

    With a stale or missing VIX (vix_fresh=False): no new dip buys and the core stays as it was. Exits still run."""
    syms = list(s["universe"])
    days = [b.t.date() for b in bars_by_sym[syms[0]]]
    for u in syms:
        if [b.t.date() for b in bars_by_sym[u]] != days:
            raise ValueError(f"{u}: bars are not date-aligned")
    if len(days) < 2:
        raise ValueError("not enough bars")
    rows, on = [], {}
    for u in syms:
        t = track(bars_by_sym[u], vix, s)
        now, before = t.want[-1], t.want[-2]
        blocked = False
        if now and not before and not vix_fresh:
            now, blocked = False, True
        on[u] = now
        action = "buy" if now and not before else "hold" if now else "sell" if before else "none"
        rows.append({"sym": u, "etf": s["universe"][u], "action": action, "why": t.why[-1] if action == "buy" else
                     ("VIX unavailable, buy skipped" if blocked else None),
                     "stop": t.stop[-1] if action == "hold" else None,
                     "since": days[t.since[-1]].isoformat() if action == "hold" and t.since[-1] is not None else None})
    spy = bars_by_sym[s["core"]["trend_symbol"]]
    flags = calm(spy, vix, s)
    is_calm = flags[-1] if vix_fresh else flags[-2]
    w = weights(on, is_calm, s)
    return {"as_of": days[-1].isoformat(), "vix": vix[-1], "vix_fresh": vix_fresh, "calm": is_calm, "rows": rows,
            "targets": w, "cash": max(0.0, 1.0 - sum(w.values()))}
