"""Multi-day swing lab on hourly bars built from regular-session 5-minute data.

Signals use completed hourly bars and fill at the next bar's open. Overnight gaps through a stop fill at the worse open.
If a bar touches both stop and target, the stop counts first. P&L is marked to market each hour on fixed capital.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.research.swing.intraday import COST, Sess


@dataclass
class H:
    sym: str; days: pd.DatetimeIndex; day: np.ndarray; o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; atr: np.ndarray; dhi: np.ndarray; dlo: np.ndarray; dcl: np.ndarray; dop: np.ndarray; dday: np.ndarray


def hourly(s: Sess) -> H:
    edges = [(k, min(k + 12, 78)) for k in range(0, 78, 12)]; n = len(s.days); m = len(edges)
    o = np.column_stack([s.o[:, a] for a, _ in edges]).ravel(); h = np.column_stack([s.h[:, a:b].max(axis=1) for a, b in edges]).ravel()
    l = np.column_stack([s.l[:, a:b].min(axis=1) for a, b in edges]).ravel(); c = np.column_stack([s.c[:, b - 1] for _, b in edges]).ravel()
    day = np.repeat(np.arange(n), m); pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)]); atr = pd.Series(tr).ewm(alpha=1 / 70, min_periods=35).mean().to_numpy()
    return H(s.sym, s.days, day, o, h, l, c, atr, s.h.max(axis=1), s.l.min(axis=1), s.c[:, -1], s.o[:, 0], np.arange(n))


def engine(b: H, side, stop, target, hold, trail=None, risk=.005, mult=1.0, fin=None):
    """Arrays are indexed by signal bar. trail is an ATR multiple for a chandelier stop, or NaN.
    fin is the T-bill return per session, charged on notional held overnight so ETF returns approximate futures."""
    N = len(b.c); bps = COST[b.sym] * mult / 1e4; pnl = np.zeros(N); trades = 0; t = 0
    trail = np.full(N, np.nan) if trail is None else trail
    while t < N - 1:
        sd = int(side[t])
        if not sd or not np.isfinite(stop[t]):
            t += 1; continue
        k = t + 1; e = b.o[k]; st = stop[t]; dist = (e - st) * sd
        if dist <= 0 or dist < .25 * b.atr[t] or not np.isfinite(b.atr[t]):
            t += 1; continue
        w = min(2.0, risk * e / dist); tg = target[t]; last = min(N - 1, k + int(hold[t]) - 1); tk = trail[t]; prev = e
        pnl[k] -= bps * w; trades += 1; x = last
        for i in range(k, last + 1):
            hit = None
            if sd > 0 and b.l[i] <= st: hit = min(st, b.o[i])
            elif sd < 0 and b.h[i] >= st: hit = max(st, b.o[i])
            elif np.isfinite(tg) and ((sd > 0 and b.h[i] >= tg) or (sd < 0 and b.l[i] <= tg)): hit = tg
            if hit is not None:
                pnl[i] += sd * (hit / prev - 1) * w - bps * w; x = i; break
            pnl[i] += sd * (b.c[i] / prev - 1) * w; prev = b.c[i]
            if fin is not None and i < last and b.day[i + 1] != b.day[i]:
                pnl[i] -= sd * w * fin[b.day[i]]  # long pays financing, short receives it
            if np.isfinite(tk):
                st = max(st, b.c[i] - tk * b.atr[i]) if sd > 0 else min(st, b.c[i] + tk * b.atr[i])
            if i == last:
                pnl[i] -= bps * w
        t = x + 1
    return pd.Series(pnl).groupby(b.day).sum().to_numpy(), trades


def blank(n):
    return np.zeros(n, int), np.full(n, np.nan), np.full(n, np.nan), np.full(n, 35.0), np.full(n, np.nan)


def donchian(b, n=70, k=3.0, direction=0):
    N = len(b.c); sd, st, tg, ho, tr = blank(N); hi = pd.Series(b.h).rolling(n).max().shift(1).to_numpy(); lo = pd.Series(b.l).rolling(n).min().shift(1).to_numpy()
    u = b.c > hi; d = b.c < lo
    if direction >= 0: sd[u] = 1; st[u] = b.c[u] - k * b.atr[u]
    if direction <= 0: sd[d] = -1; st[d] = b.c[d] + k * b.atr[d]
    ho[:] = 350; tr[:] = k
    return sd, st, tg, ho, tr


def by_day(b, x):
    return np.asarray(x)[b.day]


def last_bar(b):
    return np.r_[b.day[1:] != b.day[:-1], True]


def pullback(b, ma=50, lows=3, rr=2.0, hold=35):
    """Daily uptrend, a multi-day pullback, then an hourly close back above yesterday's high."""
    N = len(b.c); sd, st, tg, ho, tr = blank(N); cl = pd.Series(b.dcl); mm = cl.rolling(ma).mean()
    up = (cl > mm).shift(1).fillna(False).astype(bool).to_numpy(); dn = (cl < mm).shift(1).fillna(False).astype(bool).to_numpy()
    lo3 = pd.Series(b.dlo).rolling(lows).min().shift(1).to_numpy(); hi3 = pd.Series(b.dhi).rolling(lows).max().shift(1).to_numpy()
    fell = (cl.shift(1) < cl.shift(lows + 1)).to_numpy(); rose = (cl.shift(1) > cl.shift(lows + 1)).to_numpy()
    ph, pl = np.r_[np.nan, b.dhi[:-1]][b.day], np.r_[np.nan, b.dlo[:-1]][b.day]
    L = by_day(b, up & fell) & (b.c > ph); S = by_day(b, dn & rose) & (b.c < pl)
    sd[L] = 1; st[L] = lo3[b.day][L]; sd[S] = -1; st[S] = hi3[b.day][S]
    risk = np.abs(b.c - st); tg[L] = b.c[L] + rr * risk[L]; tg[S] = b.c[S] - rr * risk[S]; ho[:] = hold
    return sd, st, tg, ho, tr


def compression(b, kind="nr7", rr=2.0, hold=21):
    """After an unusually narrow day (or inside day), trade the break of that day's range."""
    N = len(b.c); sd, st, tg, ho, tr = blank(N); rng = b.dhi - b.dlo
    flag = rng <= pd.Series(rng).rolling(7).min().to_numpy() if kind == "nr7" else np.r_[False, (b.dhi[1:] < b.dhi[:-1]) & (b.dlo[1:] > b.dlo[:-1])]
    prior = np.r_[False, flag[:-1]][b.day]; ph, pl = np.r_[np.nan, b.dhi[:-1]][b.day], np.r_[np.nan, b.dlo[:-1]][b.day]
    L = prior & (b.c > ph); S = prior & (b.c < pl)
    sd[L] = 1; st[L] = pl[L]; sd[S] = -1; st[S] = ph[S]; risk = np.abs(b.c - st); tg[L] = b.c[L] + rr * risk[L]; tg[S] = b.c[S] - rr * risk[S]; ho[:] = hold
    return sd, st, tg, ho, tr


def sweep(b, rr=2.0, hold=14, trend=False):
    """Price runs past yesterday's high or low, then an hourly bar closes back inside: trade the reversal."""
    N = len(b.c); sd, st, tg, ho, tr = blank(N); ph, pl = np.r_[np.nan, b.dhi[:-1]][b.day], np.r_[np.nan, b.dlo[:-1]][b.day]
    S = (b.h > ph) & (b.c < ph); L = (b.l < pl) & (b.c > pl)
    if trend:
        mm = pd.Series(b.dcl).rolling(50).mean(); up = (pd.Series(b.dcl) > mm).shift(1).fillna(False).astype(bool).to_numpy()[b.day]; L &= up; S &= ~up
    sd[L] = 1; st[L] = b.l[L] - .1 * b.atr[L]; sd[S] = -1; st[S] = b.h[S] + .1 * b.atr[S]
    risk = np.abs(b.c - st); tg[L] = b.c[L] + rr * risk[L]; tg[S] = b.c[S] - rr * risk[S]; ho[:] = hold
    return sd, st, tg, ho, tr


def week_range(b, rr=None):
    """Break of Monday's range, held until the end of the week or a stop at the far side."""
    N = len(b.c); sd, st, tg, ho, tr = blank(N); dd = pd.Series(b.days); wk = dd.dt.to_period("W").to_numpy(); first = np.r_[True, wk[1:] != wk[:-1]]
    mh, ml = np.full(len(dd), np.nan), np.full(len(dd), np.nan); ch, cl = np.nan, np.nan; rem = np.zeros(len(dd))
    for i in range(len(dd)):
        if first[i]:
            ch, cl = b.dhi[i], b.dlo[i]
        else:
            mh[i], ml[i] = ch, cl
    for i in range(len(dd) - 1, -1, -1):
        rem[i] = 1 if i == len(dd) - 1 or wk[i + 1] != wk[i] else rem[i + 1] + 1
    H_, L_ = mh[b.day], ml[b.day]; U = b.c > H_; D = b.c < L_
    sd[U] = 1; st[U] = L_[U]; sd[D] = -1; st[D] = H_[D]; left = rem[b.day] * 7 - (np.arange(N) % 7) - 1
    ho[:] = np.maximum(left, 1)
    if rr:
        risk = np.abs(b.c - st); tg[U] = b.c[U] + rr * risk[U]; tg[D] = b.c[D] - rr * risk[D]
    return sd, st, tg, ho, tr
