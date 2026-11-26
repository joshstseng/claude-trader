"""Reported after the final test; nothing here changes the frozen rule.
1. Whole MNQ contracts on Nasdaq-100 index prices, 2020 to Oct 2026, by account size.
2. The same frozen rule on other markets, including forex and oil ETF stand-ins.
"""
from datetime import date

import numpy as np
import pandas as pd

from app.backtest import histdata
from app.research.swing.intraday import COST, Sess, load, sharpe, span
from app.research.swing.x22_audit import rewrite


def nsx():
    x = pd.DataFrame(histdata.load_1m(date(2020, 1, 1), date(2026, 10, 31), "NSXUSD"), columns=["t", "o", "h", "l", "c"])
    t = pd.to_datetime(x.t, unit="s", utc=True).dt.tz_convert("America/New_York")
    x["d"] = t.dt.tz_localize(None).dt.normalize(); x["k"] = (t.dt.hour * 60 + t.dt.minute - 570) // 5
    x = x[(x.k >= 0) & (x.k < 78)]
    g = x.groupby(["d", "k"]).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()
    n = g.groupby("d").k.count(); g = g[g.d.isin(n[n >= 74].index)]
    days = pd.DatetimeIndex(sorted(g.d.unique())); p = pd.Series(np.arange(len(days)), index=days)
    A = {c: np.full((len(days), 78), np.nan) for c in "ohlc"}
    for c in "ohlc":
        A[c][g.d.map(p).to_numpy(), g.k.to_numpy()] = g[c].to_numpy()
    c = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy(); o, h, l = (np.where(np.isnan(A[k]), c, A[k]) for k in "ohl")
    cl = pd.Series(c[:, -1], index=days)
    return Sess("NQ", days, o, h, l, c, np.ones_like(c), cl.pct_change().ewm(span=20, min_periods=10).std().shift(1).to_numpy(), cl.shift(1).to_numpy())


def mnq(s, capital, slip_ticks=1.0, look=14):
    """Fixed account size, whole contracts, $2 per point, slippage in ticks plus $0.75 fee per contract per side."""
    side_cost = slip_ticks * .25 * 2 + .75
    out = np.zeros(len(s.days)); ct = np.zeros(len(s.days)); mv = np.abs(s.c / s.o[:, 0, None] - 1); tr = 0
    for i in range(look, len(s.days)):
        v = s.vol[i]
        if not np.isfinite(v) or v <= 0 or not np.isfinite(s.prev[i]): continue
        n = int(np.floor(min(2.0, .01 / v) * capital / (s.o[i, 0] * 2)))
        if n < 1: continue
        b = np.nanmean(mv[i - look:i], axis=0); U, L = max(s.o[i, 0], s.prev[i]) * (1 + b), min(s.o[i, 0], s.prev[i]) * (1 - b)
        st, en, day = 0, 0.0, 0.0
        for k in range(5, 76, 6):
            want = 1 if s.c[i, k] > U[k] else -1 if s.c[i, k] < L[k] else 0
            if want == st: continue
            f = s.o[i, k + 1]
            if st: day += st * (f - en) * 2 * n - side_cost * n
            st = want
            if st: en = f; day -= side_cost * n; tr += n
        if st: day += st * (s.c[i, 77] - en) * 2 * n - side_cost * n
        out[i] = day; ct[i] = n
    return pd.Series(out, index=s.days), pd.Series(ct, index=s.days), tr


if __name__ == "__main__":
    s = nsx()
    print("1. Whole MNQ contracts, fixed account, Jan 2020 to Oct 2026")
    print(f"{'account':>9}{'avg cts':>8}{'days traded':>12}{'$/yr':>10}{'%/yr':>7}{'Sharpe':>8}{'max DD $':>10}{'DD %':>7}{'worst day':>10}{'2 ticks %/yr':>13}{'4 ticks %/yr':>13}")
    for cap in (10000, 25000, 50000, 100000, 250000):
        r, c, tr = mnq(s, cap); r2 = mnq(s, cap, 2)[0]; r4 = mnq(s, cap, 4)[0]; e = r.cumsum(); dd = (e - e.cummax()).min()
        print(f"{cap:>9,}{c[c>0].mean() if (c>0).any() else 0:8.1f}{(c>0).mean():12.0%}{r.mean()*252:10,.0f}{r.mean()*252/cap*100:7.1f}{sharpe(r):8.2f}{dd:10,.0f}{dd/cap*100:7.1f}{r.min():10,.0f}{r2.mean()*252/cap*100:13.1f}{r4.mean()*252/cap*100:13.1f}")
    r, c, _ = mnq(s, 50000); print("$50k by year:", r.groupby(r.index.year).sum().round(0).astype(int).to_dict())

    print("\n2. Same frozen rule on other markets, cost per side from the micro contract")
    C = {**COST, "FXE": 1.4, "FXY": 1.7, "FXB": 1.4, "FXA": 2.4}
    print(f"{'market':<7}{'sessions':>9}{'dev':>7}{'val':>7}{'final':>7}{'final %/yr':>11}")
    for m, b in C.items():
        x = load(m); out = []
        for w in ("dev", "val", "final"):
            a, z = span(x, w); y = rewrite(x, a, z, bps=b)[a:z]; out.append(y)
        print(f"{m:<7}{len(x.days):>9}{sharpe(out[0]):7.2f}{sharpe(out[1]):7.2f}{sharpe(out[2]):7.2f}{out[2].mean()*252*100:11.1f}")
