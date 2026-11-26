"""Asia-session lab (FROZEN_ASIA.md). HistData 1-minute bid bars in fixed EST; session 19:00-03:00 EST = 480 minutes."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/bars/lab/intraday/histdata/raw")
CACHE = Path("data/bars/lab/intraday/histdata")
COST = {"USDJPY": .5, "EURUSD": .5, "AUDUSD": .8, "XAUUSD": .8}
N = 480
WINDOWS = {"dev": (2016, 2019), "val": (2020, 2022), "final": (2023, 2026)}


def minutes(sym: str) -> pd.DataFrame:
    """All 1-minute bars for sym, indexed by naive EST time. Cached as .pkl after the first parse."""
    cache = CACHE / f"{sym}_1m.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    parts = []
    for f in sorted(RAW.glob(f"{sym}_*.zip")):
        with zipfile.ZipFile(f) as z:
            name = next(n for n in z.namelist() if n.endswith(".csv"))
            parts.append(pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None, names=["t", "o", "h", "l", "c", "v"]))
    x = pd.concat(parts)
    t = pd.to_datetime(x.pop("t"), format="%Y%m%d %H%M%S")
    # HistData's stamps are New York local time WITH daylight saving (checked: Sunday opens at 17:00 and gold's
    # daily break ends at 18:00 in summer and winter). Convert to UTC, then to fixed EST (UTC-5) for the session grid.
    local = pd.DatetimeIndex(t).tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    x.index = local.tz_convert("UTC").tz_localize(None) - pd.Timedelta(hours=5)
    x = x[x.index.notna()]
    x = x[~x.index.duplicated()].sort_index().drop(columns="v")
    x.to_pickle(cache)
    return x


@dataclass
class Sess:
    sym: str
    days: pd.DatetimeIndex          # session label = the calendar date the session ends on
    o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray
    d20: np.ndarray                 # +1 / -1 / 0: 19:00 price vs the last 20 sessions' 19:00 prices
    h1: np.ndarray                  # +1 / -1 / 0: hourly EMA50 trend at 19:00
    e9: np.ndarray; e20: np.ndarray  # 5-minute EMAs (continuous), session grid of 96


def sessions(sym: str) -> Sess:
    m = minutes(sym)
    start = m.index.normalize() + pd.Timedelta(hours=19)
    # each minute's session: 19:00 (day D-1) to 02:59 (day D) -> label D
    t = m.index
    hm = t.hour * 60 + t.minute
    lab = pd.DatetimeIndex(np.where(hm >= 19 * 60, (t.normalize() + pd.Timedelta(days=1)).values, t.normalize().values))
    k = np.where(hm >= 19 * 60, hm - 19 * 60, hm + 5 * 60)
    keep = (hm >= 19 * 60) | (hm < 3 * 60)
    x = m[keep].assign(lab=lab[keep], k=k[keep])
    cnt = x.groupby("lab").k.count()
    days = pd.DatetimeIndex(sorted(cnt[cnt >= 400].index))
    x = x[x.lab.isin(days)]
    pos = pd.Series(np.arange(len(days)), index=days)
    A = {c: np.full((len(days), N), np.nan) for c in "ohlc"}
    i, j = x.lab.map(pos).to_numpy(), x.k.to_numpy()
    for c in "ohlc":
        A[c][i, j] = x[c].to_numpy()
    c = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy()
    o, h, l = (np.where(np.isnan(A[q]), c, A[q]) for q in "ohl")
    # trend at 19:00
    first = pd.Series(o[:, 0], index=days)
    avg20 = first.rolling(20).mean().shift(1)
    d20 = np.sign(first - avg20).fillna(0).to_numpy()
    hr = m.c.resample("1h").last().dropna()
    ema50 = hr.ewm(span=50, adjust=False).mean()
    at = days - pd.Timedelta(hours=6)                                    # the hour bar 18:00-18:59 of the day before
    e_now = ema50.reindex(at, method="ffill").to_numpy()
    e_old = ema50.reindex(at - pd.Timedelta(hours=5), method="ffill").to_numpy()
    p_now = hr.reindex(at, method="ffill").to_numpy()
    h1 = np.where((e_now > e_old) & (p_now > e_now), 1, np.where((e_now < e_old) & (p_now < e_now), -1, 0))
    # 5-minute EMAs, continuous over all hours, sampled on the session grid
    c5 = m.c.resample("5min").last().dropna()
    e9s, e20s = c5.ewm(span=9, adjust=False).mean(), c5.ewm(span=20, adjust=False).mean()
    grid = (days - pd.Timedelta(hours=5)).values[:, None] + (np.arange(96) * 5 * 60e9).astype("timedelta64[ns]")
    e9 = e9s.reindex(pd.DatetimeIndex(grid.ravel()), method="ffill").to_numpy().reshape(len(days), 96)
    e20 = e20s.reindex(pd.DatetimeIndex(grid.ravel()), method="ffill").to_numpy().reshape(len(days), 96)
    return Sess(sym, days, o, h, l, c, d20, h1, e9, e20)


def _roll(x, n, fn):
    from numpy.lib.stride_tricks import sliding_window_view as win
    out = np.full_like(x, np.nan)
    out[:, n - 1:] = fn(win(x, n, axis=1), axis=2)
    return out


def _shift(x, n):
    out = np.full_like(x, np.nan)
    out[:, n:] = x[:, :-n]
    return out


def bars5(s: Sess):
    n = len(s.days)
    r = lambda x: x.reshape(n, 96, 5)                                           # noqa: E731
    return r(s.o)[:, :, 0], r(s.h).max(2), r(s.l).min(2), r(s.c)[:, :, -1]


def trend_signals(s: Sess, trend: str, entry: str):
    """Family T on the 1-minute grid: (long, short, long stop, short stop, long rule exit, short rule exit)."""
    o5, h5, l5, c5 = bars5(s)
    tr = (s.d20 if trend == "d20" else s.h1)[:, None]
    lo3, hi3, lo5, hi5 = _roll(l5, 3, np.min), _roll(h5, 3, np.max), _roll(l5, 5, np.min), _roll(h5, 5, np.max)
    with np.errstate(invalid="ignore"):
        if entry == "ema":
            e9, e20 = s.e9, s.e20
            e20p = _shift(e20, 5)
            L = (e9 > e20) & (c5 > e20) & (e20 > e20p) & (lo3 <= e9) & (c5 > _shift(h5, 1)) & (c5 > e9)
            S = (e9 < e20) & (c5 < e20) & (e20 < e20p) & (hi3 >= e9) & (c5 < _shift(l5, 1)) & (c5 < e9)
            xl, xs = c5 < e20, c5 > e20
        else:
            tp = (s.h + s.l + s.c) / 3
            tw = (np.cumsum(tp, 1) / np.arange(1, N + 1))[:, 4::5]
            hi6, lo6 = _roll(h5, 6, np.max), _roll(l5, 6, np.min)
            L = (c5 > tw) & (hi6 >= tw * 1.001) & (lo3 <= tw * 1.0002) & (c5 > _shift(h5, 1))
            S = (c5 < tw) & (lo6 <= tw * .999) & (hi3 >= tw * .9998) & (c5 < _shift(l5, 1))
            xl, xs = c5 < tw, c5 > tw
        L, S = L & (tr > 0), S & (tr < 0)
    n = len(s.days)

    def up(x, fill):
        out = np.full((n, N), fill, dtype=np.asarray(x).dtype)
        out[:, 4::5] = x
        return out
    return up(L, False), up(S, False), up(lo5, np.nan), up(hi5, np.nan), up(xl, False), up(xs, False)


def simulate(s: Sess, sig, exit_r, min_risk, cost_bp=None, stop_bp=.3, rows=None, first=30, last=420, max_trades=3):
    L, S, sl, ss, xl, xs = sig
    cost = (COST[s.sym] if cost_bp is None else cost_bp) / 1e4
    extra = stop_bp / 1e4
    out = []
    for i in (range(len(s.days)) if rows is None else rows):
        cands = sorted([(t, 1) for t in np.flatnonzero(L[i, first:last + 1]) + first] +
                       [(t, -1) for t in np.flatnonzero(S[i, first:last + 1]) + first])
        if not cands:
            continue
        o, h, lo, c = s.o[i], s.h[i], s.l[i], s.c[i]
        free = n = 0
        for t, side in cands:
            if t < free or n >= max_trades:
                continue
            e = t + 1
            entry = o[e]
            stop = (sl[i, t] - 1e-9 if side == 1 else ss[i, t] + 1e-9)
            if not np.isfinite(stop):
                continue
            risk = side * (entry - stop)
            if risk <= 0 or not (min_risk <= risk / entry <= .006):
                continue
            target = entry + side * exit_r * risk if exit_r != "rule" else None
            px = why = None
            for k in range(e, N):
                if (side == 1 and lo[k] <= stop) or (side == -1 and h[k] >= stop):
                    gap = (side == 1 and o[k] <= stop) or (side == -1 and o[k] >= stop)
                    px, why = (o[k] if gap else stop), "stop"; break
                if target is not None and ((side == 1 and h[k] >= target) or (side == -1 and lo[k] <= target)):
                    gap = (side == 1 and o[k] >= target) or (side == -1 and o[k] <= target)
                    px, why = (o[k] if gap and k > e else target), "target"; break
                if k == N - 1:
                    px, why = c[k], "flat"; break
                if exit_r == "rule" and (xl[i, k] if side == 1 else xs[i, k]):
                    px, why, k = o[k + 1], "rule", k + 1; break
            gross = side * (px - entry)
            costs = cost * (entry + px) + (extra * px if why == "stop" else 0)
            out.append((i, side, t, k, entry, stop, px, why, gross / risk, (gross - costs) / risk))
            n += 1
            free = k + 1
    return pd.DataFrame(out, columns=["day", "side", "sig", "out", "entry", "stop", "exit", "why", "r_gross", "r"])


def stats_r(s: Sess, tr: pd.DataFrame, span, risk=.0025) -> dict:
    idx = np.flatnonzero((s.days.year >= span[0]) & (s.days.year <= span[1]))
    t = tr[tr.day.isin(idx)]
    daily = pd.Series(0.0, index=idx)
    if len(t):
        daily = daily.add(t.groupby("day").r.sum() * risk, fill_value=0)
    sd = daily.std()
    win_, loss = t.r[t.r > 0].sum(), -t.r[t.r <= 0].sum()
    yrs = t.r.groupby(s.days.year[t.day.to_numpy()]).sum() if len(t) else pd.Series(dtype=float)
    eq = daily.cumsum()
    return {"trades": len(t), "avg_r": float(t.r.mean()) if len(t) else 0.0,
            "avg_r_gross": float(t.r_gross.mean()) if len(t) else 0.0, "win": float((t.r > 0).mean()) if len(t) else 0.0,
            "pf": float(win_ / loss) if loss else float("inf"), "sharpe": float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
            "ann": float(daily.mean() * 252), "maxdd": float((eq - eq.cummax()).min()),
            "years": {int(k): round(float(v), 1) for k, v in yrs.items()}}


def gotobi_days(days: pd.DatetimeIndex) -> np.ndarray:
    """Sessions that are a gotobi settlement day (Tokyo date = session label; weekends roll back; JP holidays ignored)."""
    have = set(days)
    out = np.zeros(len(days), bool)
    pos = {d: i for i, d in enumerate(days)}
    for m in pd.period_range(days[0], days[-1], freq="M"):
        last = m.days_in_month
        for dd in (5, 10, 15, 20, 25, 30 if last >= 30 else last):
            g = pd.Timestamp(m.year, m.month, dd)
            for back in range(0, 7):
                x = g - pd.Timedelta(days=back)
                if x in have:
                    out[pos[x]] = True
                    break
    return out


def session_returns(s: Sess, kind: str, usd_long_sign: int = 1) -> np.ndarray:
    """Per-session gross return of the fixed-time trades (families F and G)."""
    if kind == "pre":
        return usd_long_sign * (s.c[:, 54] / s.o[:, 0] - 1)
    if kind == "post":
        return -usd_long_sign * (s.c[:, 119] / s.o[:, 56] - 1)
    if kind == "asia":
        return s.c[:, N - 1] / s.o[:, 0] - 1
    raise ValueError(kind)


def stats_ret(s: Sess, ret: np.ndarray, take: np.ndarray, span, cost_bp) -> dict:
    idx = (s.days.year >= span[0]) & (s.days.year <= span[1])
    r = np.where(take, ret - 2 * cost_bp / 1e4, 0.0)[idx]
    trades = r[take[idx]]
    sd = r.std()
    yrs = pd.Series(r, index=s.days[idx]).groupby(s.days[idx].year).sum()
    return {"trades": int(take[idx].sum()), "avg_bp": float(trades.mean() * 1e4) if len(trades) else 0.0,
            "win": float((trades > 0).mean()) if len(trades) else 0.0,
            "pf": float(trades[trades > 0].sum() / -trades[trades <= 0].sum()) if (trades <= 0).any() else float("inf"),
            "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0, "ann_at_10vol": float(r.mean() / sd * .10 * np.sqrt(252)) if sd > 0 else 0.0,
            "years_bp": {int(k): round(float(v) * 1e4) for k, v in yrs.items()}}


def band_session_returns(s: Sess, m: float, chk: int, exit_: str, flt: str, cost_bp=None):
    """B2: per-session net return at 1x and trade count."""
    cost = (COST[s.sym] if cost_bp is None else cost_bp) / 1e4
    o5, h5, l5, c5 = bars5(s)
    dev = np.abs(c5 / s.o[:, :1] - 1)
    sig = pd.DataFrame(dev).rolling(14).mean().shift(1).to_numpy()                # per bar k, prior 14 sessions
    tp = (s.h + s.l + s.c) / 3
    tw = (np.cumsum(tp, 1) / np.arange(1, N + 1))[:, 4::5]
    every = chk // 5
    checks = set(range(5, 91, every))                                            # 5m bar 5 closes 19:30; bar 89 closes 02:30
    out, ntr = np.zeros(len(s.days)), np.zeros(len(s.days), int)
    for i in range(len(s.days)):
        if not np.isfinite(sig[i]).all():
            continue
        up, dn = s.o[i, 0] * (1 + m * sig[i]), s.o[i, 0] * (1 - m * sig[i])
        tr = s.d20[i]
        pos, entry, pnl, n = 0, 0.0, 0.0, 0
        for b in range(96):
            want = pos
            if exit_ == "twap" and pos and ((pos > 0 and c5[i, b] < tw[i, b]) or (pos < 0 and c5[i, b] > tw[i, b])):
                want = 0
            if b in checks:
                w = 1 if c5[i, b] > up[b] else -1 if c5[i, b] < dn[b] else 0
                if flt == "d20" and w != 0 and w != tr:
                    w = 0
                if not (exit_ == "twap" and want == 0 and pos != 0 and w == pos):
                    want = w
            if b == 95 or want != pos:
                k = 5 * b + 5                                                    # next 1m open
                px = s.c[i, N - 1] if (b == 95 or k >= N) else s.o[i, k]
                if pos:
                    pnl += pos * (px / entry - 1) - cost
                if b == 95:
                    break
                pos = want
                if pos:
                    entry, n = px, n + 1
                    pnl -= cost
        out[i], ntr[i] = pnl, n
    return out, ntr


def momentum_session_returns(s: Sess, k: float, exit_: str, flt: str, cost_bp=None):
    """B1: per-session net return at 1x and whether it traded."""
    cost = (COST[s.sym] if cost_bp is None else cost_bp) / 1e4
    r1 = s.c[:, 59] / s.o[:, 0] - 1
    s1 = pd.Series(np.abs(r1)).rolling(14).mean().shift(1).to_numpy()
    side = np.where(np.abs(r1) >= k * s1, np.sign(r1), 0)
    if flt == "d20":
        side = np.where(side == s.d20, side, 0)
    out = np.zeros(len(s.days))
    for i in np.flatnonzero(side != 0):
        e, op, px = s.o[i, 60], s.o[i, 0], s.c[i, N - 1]
        if exit_ == "stop":
            seg = s.l[i, 60:] if side[i] > 0 else s.h[i, 60:]
            hit = np.flatnonzero(seg <= op) if side[i] > 0 else np.flatnonzero(seg >= op)
            if len(hit):
                j = 60 + hit[0]
                px = min(s.o[i, j], op) if side[i] > 0 else max(s.o[i, j], op)
        out[i] = side[i] * (px / e - 1) - 2 * cost
    return out, (side != 0).astype(int)


def stats_sess(s: Sess, ret: np.ndarray, ntr: np.ndarray, span) -> dict:
    idx = (s.days.year >= span[0]) & (s.days.year <= span[1])
    r, n = ret[idx], ntr[idx]
    traded = r[n > 0]
    sd = r.std()
    yrs = pd.Series(r, index=s.days[idx]).groupby(s.days[idx].year).sum()
    return {"trades": int(n.sum()), "sessions_traded": int((n > 0).sum()), "avg_bp_session": float(traded.mean() * 1e4) if len(traded) else 0.0,
            "pf": float(traded[traded > 0].sum() / -traded[traded <= 0].sum()) if (traded <= 0).any() else float("inf"),
            "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0, "ann_1x": float(r.mean() * 252),
            "years_bp": {int(k): round(float(v) * 1e4) for k, v in yrs.items()}}


def fade_session_returns(s: Sess, m: float, target: str, stop_mult: float, flt: str, cost_bp=None, stop_bp=.3):
    """Round C: per-session net return at 1x and trade count."""
    cost = (COST[s.sym] if cost_bp is None else cost_bp) / 1e4
    extra = stop_bp / 1e4
    o5, h5, l5, c5 = bars5(s)
    sig = pd.DataFrame(np.abs(c5 / s.o[:, :1] - 1)).rolling(14).mean().shift(1).to_numpy()
    tp = (s.h + s.l + s.c) / 3
    tw1 = np.cumsum(tp, 1) / np.arange(1, N + 1)
    out, ntr = np.zeros(len(s.days)), np.zeros(len(s.days), int)
    for i in range(len(s.days)):
        if not np.isfinite(sig[i]).all():
            continue
        op = s.o[i, 0]
        up, dn = op * (1 + m * sig[i]), op * (1 - m * sig[i])
        pnl, n, free = 0.0, 0, 0
        for b in range(5, 85):                                                   # bar 5 closes 19:30, bar 84 closes 02:05
            t = 5 * b + 4
            if t < free or n >= 2:
                continue
            side = -1 if c5[i, b] > up[b] else 1 if c5[i, b] < dn[b] else 0
            if side == 0 or (flt == "trend" and side != s.d20[i]):
                continue
            e = t + 1
            entry = s.o[i, e]
            dist = abs(entry - op)
            if dist <= 0 or (side > 0 and entry >= op) or (side < 0 and entry <= op):
                continue
            stop = entry - side * stop_mult * dist
            px = why = None
            for k in range(e, N):
                if (side > 0 and s.l[i, k] <= stop) or (side < 0 and s.h[i, k] >= stop):
                    gap = (side > 0 and s.o[i, k] <= stop) or (side < 0 and s.o[i, k] >= stop)
                    px, why = (s.o[i, k] if gap else stop), "stop"; break
                if target == "open" and ((side > 0 and s.h[i, k] >= op) or (side < 0 and s.l[i, k] <= op)):
                    gap = (side > 0 and s.o[i, k] >= op) or (side < 0 and s.o[i, k] <= op)
                    px, why = (s.o[i, k] if gap and k > e else op), "target"; break
                if k == N - 1:
                    px, why = s.c[i, k], "flat"; break
                if target == "twap" and k % 5 == 4 and ((side > 0 and s.c[i, k] >= tw1[i, k]) or (side < 0 and s.c[i, k] <= tw1[i, k])):
                    px, why, k = s.o[i, k + 1], "target", k + 1; break
            pnl += side * (px / entry - 1) - 2 * cost - (extra if why == "stop" else 0)
            n += 1
            free = k + 1
        out[i], ntr[i] = pnl, n
    return out, ntr
