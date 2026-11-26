"""5-minute regular-session lab. Signals use completed bars, fills occur at the next bar's open, and stops beat targets inside a bar."""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DIR = Path("data/bars/lab/intraday/alpaca")
# bps per side: one futures tick + $0.75 fee on the micro contract, rounded up
COST = {"SPY": 1.0, "QQQ": .6, "IWM": 1.5, "GLD": 1.0, "SLV": 2.5, "USO": 3.0, "TLT": 1.0}
WINDOWS = {"dev": ("2016-01-01", "2019-12-31"), "val": ("2020-01-01", "2022-12-31"), "final": ("2023-01-01", "2026-10-31")}


@dataclass
class Sess:
    sym: str; days: pd.DatetimeIndex; o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; v: np.ndarray; vol: np.ndarray; prev: np.ndarray


def load(sym: str) -> Sess:
    with gzip.open(DIR / f"{sym}.json.gz", "rt") as f:
        x = pd.DataFrame(json.load(f), columns=["t", "o", "h", "l", "c", "v"])
    t = pd.to_datetime(x.t, utc=True).dt.tz_convert("America/New_York")
    x["d"] = t.dt.tz_localize(None).dt.normalize(); x["k"] = (t.dt.hour * 60 + t.dt.minute - 570) // 5
    x = x[(x.k >= 0) & (x.k < 78)]
    cnt = x.groupby("d").k.count(); keep = cnt[(cnt >= 70) & (x.groupby("d").k.max() >= 77)].index  # full, liquid sessions only
    x = x[x.d.isin(keep)]
    days = pd.DatetimeIndex(sorted(keep)); pos = pd.Series(np.arange(len(days)), index=days)
    A = {c: np.full((len(days), 78), np.nan) for c in "ohlcv"}
    i, j = x.d.map(pos).to_numpy(), x.k.to_numpy()
    for c in "ohlcv":
        A[c][i, j] = x[c].to_numpy()
    c = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy()
    o = np.where(np.isnan(A["o"]), c, A["o"]); h = np.where(np.isnan(A["h"]), c, A["h"]); l = np.where(np.isnan(A["l"]), c, A["l"])
    close = pd.Series(c[:, -1], index=days); prev = close.shift(1).to_numpy()
    vol = close.pct_change().ewm(span=20, min_periods=10).std().shift(1).to_numpy()
    return Sess(sym, days, o, h, l, c, np.nan_to_num(A["v"]), vol, prev)


def size(s: Sess, i: int) -> float:
    return 0.0 if not np.isfinite(s.vol[i]) or s.vol[i] <= 0 else min(2.0, .01 / s.vol[i])


def walk(s, i, k, side, stop=None, target=None, last=77):
    """Enter at the open of bar k. Returns (exit price, exit bar)."""
    for b in range(k, last + 1):
        if stop is not None:
            if side > 0 and s.l[i, b] <= stop:
                return min(stop, s.o[i, b]), b
            if side < 0 and s.h[i, b] >= stop:
                return max(stop, s.o[i, b]), b
        if target is not None:
            if side > 0 and s.h[i, b] >= target:
                return target, b
            if side < 0 and s.l[i, b] <= target:
                return target, b
    return s.c[i, last], last


def pnl(entry, exit_, side, sz, bps, sides=2):
    return side * (exit_ / entry - 1) * sz - sides * bps / 1e4 * sz


def orb(s, a, z, n=3, long_only=False, stop="range", rr=None, mult=1.0):
    r = np.zeros(len(s.days)); trades = 0
    for i in range(a, z):
        sz = size(s, i)
        if not sz: continue
        hi, lo = s.h[i, :n].max(), s.l[i, :n].min()
        for b in range(n, 72):
            side = 1 if s.c[i, b] > hi else -1 if s.c[i, b] < lo and not long_only else 0
            if side:
                e = s.o[i, b + 1]; st = (lo if side > 0 else hi) if stop == "range" else (hi + lo) / 2
                risk = abs(e - st)
                if risk <= 0 or (side > 0) != (e > st): break
                tg = e + side * rr * risk if rr else None
                x, _ = walk(s, i, b + 1, side, st, tg)
                r[i] = pnl(e, x, side, sz, COST[s.sym] * mult); trades += 1
                break
    return r, trades


def late_mom(s, a, z, sig_bars=6, entry=72, thresh=0.0, mult=1.0):
    r = np.zeros(len(s.days)); t = 0
    for i in range(a, z):
        sz = size(s, i)
        if not sz or not np.isfinite(s.prev[i]): continue
        m = s.c[i, sig_bars - 1] / s.prev[i] - 1
        if abs(m) <= thresh * s.vol[i] or m == 0: continue
        side = int(np.sign(m)); r[i] = pnl(s.o[i, entry], s.c[i, 77], side, sz, COST[s.sym] * mult); t += 1
    return r, t


def vwap_trend(s, a, z, every=6, mult=1.0):
    r = np.zeros(len(s.days)); t = 0
    for i in range(a, z):
        sz = size(s, i)
        if not sz: continue
        tp = (s.h[i] + s.l[i] + s.c[i]) / 3; v = np.maximum(s.v[i], 1)
        vw = np.cumsum(tp * v) / np.cumsum(v); side = 0; px = 0.0; day = 0.0
        for b in range(every - 1, 76, every):
            new = 1 if s.c[i, b] > vw[b] else -1
            if new != side:
                f = s.o[i, b + 1]
                if side: day += pnl(px, f, side, sz, COST[s.sym] * mult)
                side, px = new, f; t += 1
        if side: day += pnl(px, s.c[i, 77], side, sz, COST[s.sym] * mult)
        r[i] = day
    return r, t


def gap(s, a, z, k=1.0, fade=True, mult=1.0):
    r = np.zeros(len(s.days)); t = 0
    for i in range(a, z):
        sz = size(s, i)
        if not sz or not np.isfinite(s.prev[i]): continue
        g = s.o[i, 0] / s.prev[i] - 1
        if abs(g) < k * s.vol[i]: continue
        side = -int(np.sign(g)) if fade else int(np.sign(g)); e = s.o[i, 1]
        st = e * (1 - side * s.vol[i]); tg = s.prev[i] if fade else None
        if fade and (tg - e) * side <= 0: continue
        x, _ = walk(s, i, 1, side, st, tg); r[i] = pnl(e, x, side, sz, COST[s.sym] * mult); t += 1
    return r, t


def noise(s, a, z, look=14, every=6, vm=1.0, mult=1.0):
    r = np.zeros(len(s.days)); t = 0
    mv = np.abs(s.c / s.o[:, [0]] - 1)
    for i in range(max(a, look), z):
        sz = size(s, i)
        if not sz or not np.isfinite(s.prev[i]): continue
        band = np.nanmean(mv[i - look:i], axis=0) * vm; op = s.o[i, 0]
        up = max(op, s.prev[i]) * (1 + band); dn = min(op, s.prev[i]) * (1 - band); side = 0; px = 0.0; day = 0.0
        for b in range(every - 1, 76, every):
            c = s.c[i, b]; new = 1 if c > up[b] else -1 if c < dn[b] else side
            if side and ((side > 0 and c < up[b]) or (side < 0 and c > dn[b])): new = 0 if new == side else new
            if new != side:
                f = s.o[i, b + 1]
                if side: day += pnl(px, f, side, sz, COST[s.sym] * mult)
                side, px = new, f
                if side: t += 1
        if side: day += pnl(px, s.c[i, 77], side, sz, COST[s.sym] * mult)
        r[i] = day
    return r, t


def span(s, w):
    a, z = WINDOWS[w]
    return int(s.days.searchsorted(pd.Timestamp(a))), int(s.days.searchsorted(pd.Timestamp(z), side="right"))


def sharpe(x):
    x = np.asarray(x)
    return float(x.mean() / x.std() * np.sqrt(252)) if len(x) > 20 and x.std() > 0 else float("nan")
