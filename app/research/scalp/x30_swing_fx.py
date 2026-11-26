"""Exploratory, one look (2026-11-25): Swing v1 and v1.1 rules, unchanged, on forex and gold during New York hours
(9:30 AM-4:00 PM ET, the same 78 five-minute bars). QQQ 1-minute data is run through the same code as a check."""
import numpy as np, pandas as pd
from app.research.scalp import asia as A
from app.strategies.swing import BARS, CANDLE, LOOKBACK, Machine, update_fvg

COST = {"QQQ": .6, **A.COST}


def ny_5m(sym):
    if sym == "QQQ":
        z = np.load("data/bars/lab/intraday/alpaca/QQQ_1m.npz", allow_pickle=True)
        days = pd.DatetimeIndex(pd.to_datetime(z["days"]))
        o, h, l, c = (z[k].astype(float) for k in "ohlc")
        keep = (np.isfinite(c).sum(1) >= 370) & np.isfinite(c[:, -1])
        o, h, l, c, days = o[keep], h[keep], l[keep], c[keep], days[keep]
        c = pd.DataFrame(c).ffill(axis=1).bfill(axis=1).to_numpy()
        o, h, l = (np.where(np.isnan(x), c, x) for x in (o, h, l))
        r = lambda x: x.reshape(len(days), 78, 5)                                # noqa: E731
        return days, r(o)[:, :, 0], r(h).max(2), r(l).min(2), r(c)[:, :, -1]
    m = A.minutes(sym)                                                           # fixed EST -> New York local time
    t = (m.index + pd.Timedelta(hours=5)).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    k = ((t.hour * 60 + t.minute - 570) // 5).to_numpy()
    x = m.assign(d=t.normalize(), k=k)
    x = x[(x.k >= 0) & (x.k < 78)]
    g = x.groupby(["d", "k"]).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"))
    cnt = g.groupby(level=0).size()
    days = pd.DatetimeIndex(sorted(cnt[cnt >= 70].index))
    g = g[g.index.get_level_values(0).isin(days)]
    pos = pd.Series(np.arange(len(days)), index=days)
    O = {q: np.full((len(days), 78), np.nan) for q in "ohlc"}
    i, j = g.index.get_level_values(0).map(pos).to_numpy(), g.index.get_level_values(1).to_numpy()
    for q in "ohlc":
        O[q][i, j] = g[q].to_numpy()
    c = pd.DataFrame(O["c"]).ffill(axis=1).bfill(axis=1).to_numpy()
    o, h, l = (np.where(np.isnan(O[q]), c, O[q]) for q in "ohl")
    return days, o, h, l, c


def run(sym):
    days, O, H, L, C = ny_5m(sym)
    vol = pd.Series(C[:, -1]).pct_change().ewm(span=20, min_periods=10).std().shift(1).to_numpy()
    candles, lo, hi = [], None, None
    p1, p11 = np.zeros(len(days)), np.zeros(len(days))
    for i in range(len(days)):
        if i >= LOOKBACK and np.isfinite(vol[i]) and vol[i] > 0:
            sigma = np.nanmean(np.abs(C[i - LOOKBACK:i] / O[i - LOOKBACK:i, 0, None] - 1), axis=0)
            ctx = {"prev": float(C[i - 1, -1]), "weight": min(2.0, .01 / vol[i]), "sigma": list(sigma), "candles": candles, "lo": lo, "hi": hi}
            a, b = Machine.start(ctx, O[i, 0], True, COST[sym]), Machine.start(ctx, O[i, 0], False, COST[sym])
            for k in range(BARS):
                a.step(k, O[i], H[i], L[i], C[i]); b.step(k, O[i], H[i], L[i], C[i])
            p11[i], p1[i] = a.pnl, b.pnl
        for k in range(CANDLE - 1, BARS, CANDLE):
            candles, lo, hi = update_fvg(candles, lo, hi, H[i, k - 2:k + 1].max(), L[i, k - 2:k + 1].min(), C[i, k])
    return pd.DataFrame({"v1": p1, "v11": p11}, index=days).loc["2016-02-01":"2026-10-30"]


def dd(r):
    e = (1 + r).cumprod(); return (e / e.cummax() - 1).min()


res, yearly = {}, {}
for sym in ("QQQ", "USDJPY", "EURUSD", "AUDUSD", "XAUUSD"):
    x = run(sym); res[sym] = x
    for v in ("v1", "v11"):
        r = x[v]; yrs = len(r) / 252
        cagr = (1 + r).prod() ** (1 / yrs) - 1
        y = (1 + r).groupby(r.index.year).prod() - 1
        yearly[f"{sym} {v}"] = y * 100
        win = {w: r.loc[a:z].mean() / r.loc[a:z].std() * np.sqrt(252) for w, (a, z) in {"16-19": ("2016", "2019"), "20-22": ("2020", "2022"), "23-26": ("2023", "2026")}.items()}
        print(f"{sym:7} {v:4} CAGR {cagr*100:5.1f}%  Sharpe {r.mean()/r.std()*np.sqrt(252):5.2f}  max drop {dd(r)*100:6.1f}%  losing years {(y<0).sum():2}  "
              + "  ".join(f"{w} {s:5.2f}" for w, s in win.items()) + f"  days {len(r)}")
print("\nYear-by-year % (v1.1)")
print(pd.DataFrame({k.split()[0]: v for k, v in yearly.items() if k.endswith("v11")}).round(1).to_string())
pd.concat(res, axis=1).to_csv("app/research/scalp/x30_swing_fx_daily.csv")
