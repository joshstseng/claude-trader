"""Audit candidate 1 on 2016-2022 only: independent rewrite, later fills, and a second data source."""
from datetime import date

import numpy as np
import pandas as pd

from app.backtest import histdata
from app.research.swing.intraday import Sess, load, noise, sharpe, span


def rewrite(s, a, z, delay=1, bps=.6, look=14):
    """Written separately from intraday.noise. delay=1 fills at the next bar's open, delay=2 waits five more minutes."""
    out = np.zeros(len(s.days)); moves = np.abs(s.c / s.o[:, 0, None] - 1)
    for day in range(max(a, look), z):
        v = s.vol[day]
        if not np.isfinite(v) or v <= 0 or not np.isfinite(s.prev[day]):
            continue
        w = min(2.0, .01 / v); sigma = np.nanmean(moves[day - look:day], axis=0)
        U, L = max(s.o[day, 0], s.prev[day]) * (1 + sigma), min(s.o[day, 0], s.prev[day]) * (1 - sigma)
        state, entry, total = 0, 0.0, 0.0
        for chk in range(5, 76, 6):
            px = s.c[day, chk]
            want = 1 if px > U[chk] else (-1 if px < L[chk] else 0)
            if want == state:
                continue
            fill = s.o[day, min(chk + delay, 77)]
            if state:
                total += state * (fill / entry - 1) * w - bps / 1e4 * w
            state = want
            if state:
                entry = fill; total -= bps / 1e4 * w
        if state:
            total += state * (s.c[day, 77] / entry - 1) * w - bps / 1e4 * w
        out[day] = total
    return out


def nsx():
    rows = histdata.load_1m(date(2020, 1, 1), date(2022, 12, 31), "NSXUSD")
    x = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c"]); t = pd.to_datetime(x.t, unit="s", utc=True).dt.tz_convert("America/New_York")
    x["d"] = t.dt.tz_localize(None).dt.normalize(); x["k"] = (t.dt.hour * 60 + t.dt.minute - 570) // 5
    x = x[(x.k >= 0) & (x.k < 78)]
    g = x.groupby(["d", "k"]).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()
    n = g.groupby("d").k.count(); g = g[g.d.isin(n[n >= 74].index)]
    days = pd.DatetimeIndex(sorted(g.d.unique())); p = pd.Series(np.arange(len(days)), index=days)
    A = {c: np.full((len(days), 78), np.nan) for c in "ohlc"}
    for c in "ohlc":
        A[c][g.d.map(p).to_numpy(), g.k.to_numpy()] = g[c].to_numpy()
    c = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy()
    o, h, l = (np.where(np.isnan(A[k]), c, A[k]) for k in "ohl")
    cl = pd.Series(c[:, -1], index=days)
    return Sess("QQQ", days, o, h, l, c, np.ones_like(c), cl.pct_change().ewm(span=20, min_periods=10).std().shift(1).to_numpy(), cl.shift(1).to_numpy())


if __name__ == "__main__":
    s = load("QQQ")
    for w in ("dev", "val"):
        a, z = span(s, w); base = noise(s, a, z, look=14, every=6, vm=1.0)[0][a:z]; re = rewrite(s, a, z)[a:z]
        print(f"{w}: original {base.mean()*252*100:.2f}%/yr Sharpe {sharpe(base):.2f} | rewrite {re.mean()*252*100:.2f}%/yr Sharpe {sharpe(re):.2f} | days differing {(np.abs(base-re)>1e-9).sum()} of {len(re)}, corr {np.corrcoef(base,re)[0,1]:.4f}")
        for d, b in ((2, .6), (3, .6), (1, 1.5), (1, 3.0), (2, 1.5)):
            y = rewrite(s, a, z, d, b)[a:z]; print(f"   fill delay {(d-1)*5:>2} min, cost {b} bp/side: {y.mean()*252*100:6.2f}%/yr  Sharpe {sharpe(y):5.2f}")
    n = nsx(); a, z = 0, len(n.days); y = rewrite(n, a, z)[a:z]; idx = n.days[a:z]
    print(f"\nSecond source, Nasdaq-100 index CFD 2020-2022: {y.mean()*252*100:.2f}%/yr Sharpe {sharpe(y):.2f}, by year {(pd.Series(y,index=idx).groupby(idx.year).sum()*100).round(1).to_dict()}, sessions {len(y)}")
    q = pd.Series(rewrite(s, *span(s, 'val'))[span(s, 'val')[0]:span(s, 'val')[1]], index=s.days[span(s, 'val')[0]:span(s, 'val')[1]])
    c = pd.concat([q, pd.Series(y, index=idx)], axis=1, join="inner"); print("daily correlation, QQQ version vs index-CFD version:", round(c.corr().iloc[0, 1], 3), "on", len(c), "days")
    x = q.sort_values(ascending=False); print(f"top 10 days give {x.head(10).sum()/x.sum():.0%} of validate profit; profit without them {(x.iloc[10:].mean()*252*100):.1f}%/yr")
