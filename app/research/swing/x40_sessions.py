"""Candidate 3: the frozen noise-band rule in the Asia and London sessions, one run."""
from datetime import date

import numpy as np
import pandas as pd

from app.backtest import histdata
from app.research.swing.intraday import sharpe


def frame(pair):
    x = pd.DataFrame(histdata.load_1m(date(2020, 1, 1), date(2026, 10, 31), pair), columns=["t", "o", "h", "l", "c"])
    t = pd.to_datetime(x.t, unit="s", utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    x["t"] = t
    return x.set_index("t").sort_index()


def session(x, start, bars):
    """5-minute matrix per session. start is minutes after midnight ET; sessions starting in the evening are labeled by their end date."""
    t = x.index; mins = t.hour * 60 + t.minute; rel = (mins - start) % 1440; keep = rel < bars * 5
    y = x[keep].copy(); rel = rel[keep]; y["k"] = rel // 5
    anchor = (y.index - pd.to_timedelta(rel, unit="m")).normalize(); y["d"] = anchor
    g = y.groupby(["d", "k"]).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()
    n = g.groupby("d").k.count(); g = g[g.d.isin(n[n >= int(bars * .9)].index)]
    days = pd.DatetimeIndex(sorted(g.d.unique())); p = pd.Series(np.arange(len(days)), index=days); A = {c: np.full((len(days), bars), np.nan) for c in "ohlc"}
    for c in "ohlc":
        A[c][g.d.map(p).to_numpy(), g.k.to_numpy()] = g[c].to_numpy()
    c = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy(); o = np.where(np.isnan(A["o"]), c, A["o"])
    return days, o, c


def rule(days, o, c, bps=1.0, look=14):
    out = np.zeros(len(days)); trades = 0; bars = c.shape[1]; mv = np.abs(c / o[:, 0, None] - 1)
    cl = pd.Series(c[:, -1], index=days); prev = cl.shift(1).to_numpy(); vol = cl.pct_change().ewm(span=20, min_periods=10).std().shift(1).to_numpy()
    for i in range(look, len(days)):
        if not np.isfinite(vol[i]) or vol[i] <= 0 or not np.isfinite(prev[i]): continue
        w = min(2.0, .01 / vol[i]); s = np.nanmean(mv[i - look:i], axis=0); U, L = max(o[i, 0], prev[i]) * (1 + s), min(o[i, 0], prev[i]) * (1 - s); st, en, day = 0, 0.0, 0.0
        for k in range(5, bars - 2, 6):
            want = 1 if c[i, k] > U[k] else -1 if c[i, k] < L[k] else 0
            if want == st: continue
            f = o[i, k + 1]
            if st: day += st * (f / en - 1) * w - bps / 1e4 * w
            st = want
            if st: en = f; day -= bps / 1e4 * w; trades += 1
        if st: day += st * (c[i, -1] / en - 1) * w - bps / 1e4 * w
        out[i] = day
    return pd.Series(out, index=days), trades


ok_all = {}
for pair in ("NSXUSD", "SPXUSD"):
    x = frame(pair)
    for name, start, bars in (("Asia 6PM-2AM ET", 18 * 60, 96), ("London 2AM-9:25AM ET", 2 * 60, 89)):
        days, o, c = session(x, start, bars); r, t = rule(days, o, c); r2, _ = rule(days, o, c, 2.0); line = []; good = True
        for lab, a, z in (("2020-22", "2020", "2022"), ("2023-Oct26", "2023", "2026")):
            y, y2 = r.loc[a:z], r2.loc[a:z]; tr = int((y != 0).sum()); e = y.cumsum()
            line.append(f"{lab}: {y.mean()*252*100:5.1f}%/yr Sharpe {sharpe(y):5.2f} DD {(e-e.cummax()).min()*100:5.1f}% active days {tr}")
            good &= sharpe(y) >= .7 and y2.sum() > 0 and tr >= 100
        print(f"{pair} {name} ({len(days)} sessions): " + " | ".join(line) + f" -> {'PASS' if good else 'FAIL'}"); ok_all[(pair, name)] = good
print("Candidate 3:", "at least one session passed" if any(ok_all.values()) else "FAIL in every session and market")
