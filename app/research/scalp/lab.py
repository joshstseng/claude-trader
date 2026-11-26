"""1-minute scalp lab for the VWAP and EMA pullback families. Rules: FROZEN_SCALP.md."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as win

NPZ = "data/bars/lab/intraday/alpaca/QQQ_1m.npz"
WINDOWS = {"dev": ("2016", "2019"), "val": ("2020", "2022"), "final": ("2023", "2026")}
FIRST, MORNING_END, LAST_ENTRY, FLAT = 15, 120, 360, 384      # 1m bar indexes from 9:30
MIN_RISK, MAX_RISK, MAX_TRADES = .0006, .0060, 3


@dataclass
class Data:
    days: pd.DatetimeIndex
    o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; v: np.ndarray


def load() -> Data:
    z = np.load(NPZ, allow_pickle=True)
    days = pd.DatetimeIndex(pd.to_datetime(z["days"]))
    o, h, l, c, v = (z[k].astype(float) for k in "ohlcv")
    keep = (np.isfinite(c).sum(1) >= 370) & np.isfinite(c[:, -1])
    o, h, l, c, v, days = o[keep], h[keep], l[keep], c[keep], v[keep], days[keep]
    c = pd.DataFrame(c).ffill(axis=1).bfill(axis=1).to_numpy()
    o, h, l = (np.where(np.isnan(x), c, x) for x in (o, h, l))
    return Data(days, o, h, l, c, np.nan_to_num(v))


def roll(x: np.ndarray, n: int, fn) -> np.ndarray:
    """Rolling fn over the last n bars within each day (nan until n bars exist)."""
    out = np.full_like(x, np.nan)
    out[:, n - 1:] = fn(win(x, n, axis=1), axis=2)
    return out


def shift(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[:, n:] = x[:, :-n]
    return out


def ema(x: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(x.ravel()).ewm(span=span, adjust=False).mean().to_numpy().reshape(x.shape)


def resample(d: Data, k: int = 5):
    n = d.c.shape[0]
    r = lambda x: x.reshape(n, 390 // k, k)                                     # noqa: E731
    return r(d.o)[:, :, 0], r(d.h).max(2), r(d.l).min(2), r(d.c)[:, :, -1]


def resample5(d: Data):
    return resample(d, 5)


def vwap_signals(d: Data, ext: float, tol: float):
    tp = (d.h + d.l + d.c) / 3
    cv = np.cumsum(d.v, 1)
    vw = np.where(cv > 0, np.cumsum(tp * d.v, 1) / np.maximum(cv, 1e-9), d.c)
    hi30, lo30 = roll(d.h, 31, np.max), roll(d.l, 31, np.min)
    lo3, hi3 = roll(d.l, 3, np.min), roll(d.h, 3, np.max)
    lo5, hi5 = roll(d.l, 5, np.min), roll(d.h, 5, np.max)
    vw30 = shift(vw, 30)
    with np.errstate(invalid="ignore"):
        L = (d.c > vw) & (vw > vw30) & (hi30 >= vw * (1 + ext)) & (lo3 <= vw * (1 + tol)) & (d.c > shift(d.h, 1))
        S = (d.c < vw) & (vw < vw30) & (lo30 <= vw * (1 - ext)) & (hi3 >= vw * (1 - tol)) & (d.c < shift(d.l, 1))
        exit_l, exit_s = d.c < vw, d.c > vw
    return L, S, lo5 - .01, hi5 + .01, exit_l, exit_s


def ema_signals(d: Data, tf: str, stop: str):
    k = {"1m": 1, "5m": 5, "15m": 15}[tf]
    o, h, l, c = (d.o, d.h, d.l, d.c) if k == 1 else resample(d, k)
    e9, e20 = ema(c, 9), ema(c, 20)
    e20p = ema(c, 20)
    e20p = np.roll(e20p.ravel(), 5).reshape(c.shape)                          # 5 bars ago, across days
    lo3, hi3, lo5, hi5 = roll(l, 3, np.min), roll(h, 3, np.max), roll(l, 5, np.min), roll(h, 5, np.max)
    with np.errstate(invalid="ignore"):
        L = (e9 > e20) & (c > e20) & (e20 > e20p) & (lo3 <= e9) & (c > shift(h, 1)) & (c > e9)
        S = (e9 < e20) & (c < e20) & (e20 < e20p) & (hi3 >= e9) & (c < shift(l, 1)) & (c < e9)
        exit_l, exit_s = c < e20, c > e20
    sl, ss = (lo5 - .01, hi5 + .01) if stop == "swing" else (e20 - .01, e20 + .01)
    if tf == "1m":
        return L, S, sl, ss, exit_l, exit_s
    n = c.shape[0]

    def up(x, fill):                                                          # bar j -> 1m bar k*j+k-1
        out = np.full((n, 390), fill, dtype=np.asarray(x).dtype)
        out[:, k - 1::k] = x
        return out
    return up(L, False), up(S, False), up(sl, np.nan), up(ss, np.nan), up(exit_l, False), up(exit_s, False)


def simulate(d: Data, sig, exit_r, sides="both", window="all", cost_bp=.6, stop_bp=.3, rows=None, min_risk=MIN_RISK):
    """Trades as a DataFrame. exit_r: a number (target in R) or 'rule'."""
    L, S, sl, ss, xl, xs = sig
    last_sig = MORNING_END if window == "morning" else LAST_ENTRY
    cost, extra = cost_bp / 1e4, stop_bp / 1e4
    out = []
    for i in (range(len(d.days)) if rows is None else rows):
        cand_l = np.flatnonzero(L[i, FIRST:last_sig + 1]) + FIRST
        cand_s = np.flatnonzero(S[i, FIRST:last_sig + 1]) + FIRST if sides == "both" else np.array([], int)
        cands = sorted([(t, 1) for t in cand_l] + [(t, -1) for t in cand_s])
        if not cands:
            continue
        o, h, lo, c = d.o[i], d.h[i], d.l[i], d.c[i]
        free, n = 0, 0
        for t, side in cands:
            if t < free or n >= MAX_TRADES or t + 1 > FLAT:
                continue
            if side == 1 and S[i, t] and sides == "both":
                continue                                                      # conflicting signals: skip
            e = t + 1
            entry = o[e]
            stop = sl[i, t] if side == 1 else ss[i, t]
            if not np.isfinite(stop):
                continue
            risk = side * (entry - stop)
            if risk <= 0 or not (min_risk <= risk / entry <= MAX_RISK):
                continue
            target = entry + side * exit_r * risk if exit_r != "rule" else None
            px, why, k = None, None, e
            for k in range(e, FLAT + 1):
                if (side == 1 and lo[k] <= stop) or (side == -1 and h[k] >= stop):
                    px = (min(o[k], stop) if side == 1 else max(o[k], stop)) if k > e else stop
                    if k == e and ((side == 1 and o[k] <= stop) or (side == -1 and o[k] >= stop)):
                        px = o[k]
                    why = "stop"; break
                if target is not None and ((side == 1 and h[k] >= target) or (side == -1 and lo[k] <= target)):
                    px = (max(o[k], target) if side == 1 else min(o[k], target)) if k > e else target
                    why = "target"; break
                if k == FLAT:
                    px, why = c[k], "flat"; break
                if exit_r == "rule" and (xl[i, k] if side == 1 else xs[i, k]):
                    px, why, k = o[k + 1], "rule", k + 1; break
            gross = side * (px - entry)
            costs = cost * entry + cost * px + (extra * px if why == "stop" else 0)
            out.append((i, side, t, k, entry, stop, px, why, gross / risk, (gross - costs) / risk, risk / entry))
            n += 1
            free = k + 1
    cols = ["day", "side", "sig", "out", "entry", "stop", "exit", "why", "r_gross", "r", "risk_pct"]
    return pd.DataFrame(out, columns=cols)


def stats(d: Data, tr: pd.DataFrame, span, risk=.0025) -> dict:
    a, z = span
    mask = (d.days.year >= int(a)) & (d.days.year <= int(z))
    idx = np.flatnonzero(mask)
    t = tr[tr.day.isin(idx)]
    daily = pd.Series(0.0, index=idx)
    if len(t):
        daily = daily.add(t.groupby("day").r.sum() * risk, fill_value=0)
    sd = daily.std()
    win_ = t.r[t.r > 0].sum(); loss = -t.r[t.r <= 0].sum()
    yrs = (t.r.groupby(d.days.year[t.day.to_numpy()]).sum() if len(t) else pd.Series(dtype=float))
    eq = daily.cumsum()
    return {"trades": len(t), "avg_r": t.r.mean() if len(t) else 0.0, "avg_r_gross": t.r_gross.mean() if len(t) else 0.0,
            "win": (t.r > 0).mean() if len(t) else 0.0, "pf": win_ / loss if loss else np.inf,
            "sharpe": daily.mean() / sd * np.sqrt(252) if sd > 0 else 0.0, "ann": daily.mean() * 252,
            "maxdd": (eq - eq.cummax()).min(), "years": {int(k): round(float(v), 1) for k, v in yrs.items()},
            "per_day": len(t) / len(idx)}


def swing_side(d: Data) -> np.ndarray:
    """Swing v1's side (1, -1, 0) at each 1-minute bar, as of the last completed 5-minute bar. Days without
    14 prior sessions are 0."""
    from app.strategies.swing import BARS, LOOKBACK, Machine
    o5, h5, l5, c5 = resample5(d)
    side = np.zeros(d.c.shape)
    closes = pd.Series(c5[:, -1])
    vol = closes.pct_change().ewm(span=20, min_periods=10).std().shift(1).to_numpy()
    for i in range(LOOKBACK, len(d.days)):
        if not np.isfinite(vol[i]) or vol[i] <= 0:
            continue
        sigma = np.nanmean(np.abs(c5[i - LOOKBACK:i] / o5[i - LOOKBACK:i, 0, None] - 1), axis=0)
        ctx = {"prev": float(c5[i - 1, -1]), "weight": 1.0, "sigma": list(sigma), "candles": [], "lo": None, "hi": None}
        m = Machine.start(ctx, o5[i, 0], False)
        for b in range(BARS):
            m.step(b, o5[i], h5[i], l5[i], c5[i])
            side[i, 5 * b + 4: 5 * b + 9] = m.side
    return side


def filtered(sig, side):
    L, S, *rest = sig
    return (L & (side > 0), S & (side < 0), *rest)


def fade_signals(d: Data, tf: str, z: float):
    """VWAP fade (FROZEN_SCALP.md round 4). Returned on the 1-minute grid."""
    tp = (d.h + d.l + d.c) / 3
    cv = np.cumsum(d.v, 1)
    vw = np.where(cv > 0, np.cumsum(tp * d.v, 1) / np.maximum(cv, 1e-9), d.c)
    k = {"1m": 1, "5m": 5}[tf]
    o, h, l, c = (d.o, d.h, d.l, d.c) if k == 1 else resample(d, k)
    v = vw if k == 1 else vw[:, k - 1::k]
    lo5, hi5 = roll(l, 5, np.min), roll(h, 5, np.max)
    with np.errstate(invalid="ignore"):
        L = (c <= v * (1 - z)) & (c > shift(h, 1))
        S = (c >= v * (1 + z)) & (c < shift(l, 1))
    n = c.shape[0]

    def up(x, fill):
        if k == 1:
            return x
        out = np.full((n, 390), fill, dtype=np.asarray(x).dtype)
        out[:, k - 1::k] = x
        return out
    L, S = up(L, False), up(S, False)
    L[:, :30] = S[:, :30] = False
    L[:, 331:] = S[:, 331:] = False                                            # 10:00 AM-3:00 PM signals
    with np.errstate(invalid="ignore"):
        return L, S, up(lo5 - .01, np.nan), up(hi5 + .01, np.nan), d.c >= vw, d.c <= vw


def flat_only(sig, side):
    L, S, *rest = sig
    return (L & (side == 0), S & (side == 0), *rest)
