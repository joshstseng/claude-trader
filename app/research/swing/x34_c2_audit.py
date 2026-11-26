"""Audit of candidate 2: separately written simulator, then whole micro contracts by account size. No settings change."""
import numpy as np
import pandas as pd

from app.research.swing.hourly import donchian, engine, hourly
from app.research.swing.intraday import COST, sharpe, span
from app.research.swing.x33_c2_fin import D, IRX, P, cut, port

# approximate dollars of notional for one micro contract, as a multiple of the ETF price, or a fixed amount
NOTIONAL = {"SPY": ("x", 50), "QQQ": ("x", 82), "IWM": ("x", 50), "GLD": ("x", 109), "SLV": ("x", 1070), "USO": ("fixed", 7000), "TLT": ("fixed", 12000)}
SCALE = 1.5 / np.sqrt(7)


def chan(b, fin, capital=None, sym=None, mult=1.0):
    """Written separately from hourly.engine. With capital set, sizes are whole contracts on a fixed account."""
    n = len(b.c); out = np.zeros(n); bp = COST[b.sym] * mult / 1e4; pos = 0.0; stop = np.nan; left = 0; trades = 0; skipped = 0; last = b.c[0]
    for t in range(71, n):
        px0 = b.c[t - 1]
        if pos:
            o, l = b.o[t], b.l[t]
            if l <= stop:
                f = min(stop, o); out[t] += pos * (f / px0 - 1) - bp * pos; pos = 0.0
            else:
                out[t] += pos * (b.c[t] / px0 - 1); left -= 1
                if left <= 0:
                    out[t] -= bp * pos; pos = 0.0
                else:
                    stop = max(stop, b.c[t] - 3 * b.atr[t])
                    if t + 1 < n and b.day[t + 1] != b.day[t]:
                        out[t] -= pos * fin[b.day[t]]
        elif b.c[t - 1] > b.h[t - 71:t - 1].max() and np.isfinite(b.atr[t - 1]):
            e = b.o[t]; st = b.c[t - 1] - 3 * b.atr[t - 1]; d = e - st
            if d > 0 and d >= .25 * b.atr[t - 1]:
                w = min(2.0, .005 * e / d)
                if capital:
                    kind, v = NOTIONAL[sym]; cn = e * v if kind == "x" else v
                    w = np.floor(w * SCALE * capital / cn) * cn / capital
                    if w <= 0:
                        skipped += 1; continue
                pos, stop, left = w, st, 350; out[t] -= bp * w; trades += 1
                if b.l[t] <= stop:
                    f = min(stop, b.o[t]); out[t] += pos * (f / e - 1) - bp * pos; pos = 0.0
                else:
                    out[t] += pos * (b.c[t] / e - 1); stop = max(stop, b.c[t] - 3 * b.atr[t]); left -= 1
                    if t + 1 < n and b.day[t + 1] != b.day[t]:
                        out[t] -= pos * fin[b.day[t]]
    return pd.Series(out).groupby(b.day).sum().to_numpy(), trades, skipped


def book(w, capital=None, mult=1.0):
    R, T, K = {}, 0, 0
    for m, s in D.items():
        a, z = span(s, w); b = hourly(cut(s, z)); f = IRX.reindex(b.days).ffill().bfill().to_numpy()
        x, t, k = chan(b, f, capital, m, mult); R[m] = pd.Series(x[a:z], index=b.days[a:z]); T += t; K += k
    return pd.DataFrame(R).fillna(0).sum(axis=1), T, K


print("1. Separate rewrite vs original, fractional sizing")
for w in ("dev", "val", "final"):
    o, _ = port(w); r = book(w)[0] * SCALE; c = pd.concat([o, r], axis=1, join="inner")
    print(f"  {w:<6} original {o.mean()*252*100:5.2f}%/yr Sharpe {sharpe(o):.2f} | rewrite {r.mean()*252*100:5.2f}%/yr Sharpe {sharpe(r):.2f} | daily corr {c.corr().iloc[0,1]:.4f}")
print("\n2. Whole micro contracts on fixed capital, with financing")
print(f"{'account':>9}{'window':>7}{'%/yr':>7}{'Sharpe':>8}{'DD %':>7}{'2x %/yr':>9}{'entries':>8}{'skipped':>8}  by year %")
for cap in (50000, 100000, 250000):
    for w in ("val", "final"):
        x, t, k = book(w, cap); y, _, _ = book(w, cap, 2.0); e = x.cumsum()
        print(f"{cap:>9,}{w:>7}{x.mean()*252*100:7.1f}{sharpe(x):8.2f}{(e-e.cummax()).min()*100:7.1f}{y.mean()*252*100:9.1f}{t:8d}{k:8d}  {(x.groupby(x.index.year).sum()*100).round(1).to_dict()}")
