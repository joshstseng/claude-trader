"""Swing v1 with early exits when a PD array is disrespected, following FROZEN_PD.md."""
import itertools

import numpy as np
import pandas as pd

from app.research.swing.intraday import load, noise, sharpe
from app.research.swing.v1x import W, bands, rng, score

s = load("QQQ"); U, D = bands(s); ND, NB = s.c.shape; CH = set(range(5, 76, 6))
O, H, L, C = (x.ravel() for x in (s.o, s.h, s.l, s.c))


def candles(tf):
    n = tf // 5; st = np.concatenate([np.arange(0, NB, n) + d * NB for d in range(ND)]); en = np.minimum(st + n, (st // NB + 1) * NB) - 1
    return O[st], np.array([H[a:b + 1].max() for a, b in zip(st, en)]), np.array([L[a:b + 1].min() for a, b in zip(st, en)]), C[en], en


def arrays(kind, tf):
    """Returns global 5-minute series of the latest long-side and short-side invalidation levels, known at each bar's close."""
    o, h, l, c, en = candles(tf); N = len(c); lo, hi = np.full(ND * NB, np.nan), np.full(ND * NB, np.nan)
    if kind == "FVG":
        for t in range(2, N):
            if l[t] > h[t - 2] and c[en[t] - en[t] + t] > l[t] * 0 and l[t - 2] > 0:
                lo[en[t]] = h[t - 2]
            if h[t] < l[t - 2]:
                hi[en[t]] = l[t - 2]
    elif kind == "Order block":
        for t in range(1, N):
            if c[t - 1] < o[t - 1] and c[t] > h[t - 1]:
                lo[en[t]] = l[t - 1]
            if c[t - 1] > o[t - 1] and c[t] < l[t - 1]:
                hi[en[t]] = h[t - 1]
    else:
        for t in range(2, N):
            if l[t - 1] < l[t - 2] and l[t - 1] < l[t]:
                lo[en[t]] = l[t - 1]
            if h[t - 1] > h[t - 2] and h[t - 1] > h[t]:
                hi[en[t]] = h[t - 1]
    valid_lo = np.where(lo < C, lo, np.nan); valid_hi = np.where(hi > C, hi, np.nan)  # an array must still be intact when it forms
    return pd.Series(valid_lo).ffill().to_numpy().reshape(ND, NB), pd.Series(valid_hi).ffill().to_numpy().reshape(ND, NB)


def run(a, z, A=None, conf=5, trail=False, reenter=True, bps=.6):
    out = np.zeros(ND); trades = early = 0; step = conf // 5
    for i in range(max(a, 14), z):
        v = s.vol[i]
        if not np.isfinite(v) or v <= 0 or not np.isfinite(s.prev[i]):
            continue
        w = min(2.0, .01 / v); side, en, day, stop, block = 0, 0., 0., np.nan, 0; c_, o_, u_, d_ = s.c[i], s.o[i], U[i], D[i]
        for b in range(5, 77):
            ex = False
            if side and A is not None and (b + 1) % step == 0:
                lv = (A[0][i, b] if side > 0 else A[1][i, b]) if trail else stop
                ex = np.isfinite(lv) and (c_[b] < lv if side > 0 else c_[b] > lv)
            want = None
            if b in CH:
                want = 1 if c_[b] > u_[b] else -1 if c_[b] < d_[b] else 0
                if want == 0:
                    block = 0
                elif want == -block:
                    block = 0
                if ex and want == side and reenter:
                    ex = False
            if ex:
                day += side * (o_[b + 1] / en - 1) * w - bps / 1e4 * w; early += 1
                if not reenter:
                    block = side
                side = 0
            if want is not None:
                if side and want != side:
                    day += side * (o_[b + 1] / en - 1) * w - bps / 1e4 * w; side = 0
                if not side and want and want != block:
                    side, en = want, o_[b + 1]; day -= bps / 1e4 * w; trades += 1
                    if A is not None:
                        lv = A[0][i, b] if side > 0 else A[1][i, b]
                        stop = lv if np.isfinite(lv) and (lv < en if side > 0 else lv > en) else np.nan
        if side:
            day += side * (c_[77] / en - 1) * w - bps / 1e4 * w
        out[i] = day
    return out, trades, early


for w in W:
    a, z = rng(s, w); print(f"control {w}: days differing from frozen v1 = {(np.abs(run(a, z)[0][a:z] - noise(s, a, z, look=14, every=6, vm=1.0)[0][a:z]) > 1e-9).sum()}")
AR = {(k, tf): arrays(k, tf) for k in ("FVG", "Order block", "Swing structure") for tf in (5, 15, 30, 60)}
base = {w: score(run(*rng(s, w))[0][rng(s, w)[0]:rng(s, w)[1]]) for w in W}
a, z = rng(s, "dev"); rows = []
for (k, tf), A in AR.items():
    for cf, tr, re in itertools.product((5, 15), (False, True), (True, False)):
        if cf > tf:
            continue
        r, t, e = run(a, z, A, cf, tr, re); r2, _, _ = run(a, z, A, cf, tr, re, bps=1.2); m = score(r[a:z]); m2 = score(r2[a:z])
        rows.append(dict(kind=k, name=f"{k} {tf}m, confirm {cf}m, {'trail' if tr else 'fixed'}, {'re-enter' if re else 'block'}", tf=tf, cf=cf, tr=tr, re=re, ret=m["ret"], sharpe=m["sharpe"], dd=m["dd"], ret2=m2["ret"], trades=t, early=e, worst=r[a:z].min() * 100))
o = pd.DataFrame(rows); o.to_pickle("data/bars/lab/intraday/x80.pkl")
print(f"\nDEV 2016-2019: v1 {base['dev']['ret']:.1f}%/yr, Sharpe {base['dev']['sharpe']:.2f}, drop {base['dev']['dd']:.1f}%")
print(f"{len(o)} variants. Beat v1 Sharpe: {(o.sharpe > base['dev']['sharpe']).sum()}. Median Sharpe {o.sharpe.median():.2f}")
print(o.groupby("kind").sharpe.median().round(2).to_dict(), "by array timeframe", o.groupby("tf").sharpe.median().round(2).to_dict(), "by confirm", o.groupby("cf").sharpe.median().round(2).to_dict(), "trail", o.groupby("tr").sharpe.median().round(2).to_dict(), "re-enter", o.groupby("re").sharpe.median().round(2).to_dict())
print(o.sort_values("sharpe", ascending=False).head(12)[["name", "ret", "sharpe", "dd", "ret2", "trades", "early", "worst"]].round(2).to_string(index=False))
el = o[(o.sharpe > base["dev"]["sharpe"]) & (o.ret2 > 0) & (o.trades >= 100)]
for _, p in el.sort_values("sharpe", ascending=False).groupby("kind", sort=False).head(1).iterrows():
    A = AR[(p.kind, p.tf)]; a, z = rng(s, "val"); r, t, e = run(a, z, A, p.cf, p.tr, p.re); v = score(r[a:z])
    print(f"\nFinalist: {p['name']}\n  2020-22: {v['ret']:.1f}%/yr Sharpe {v['sharpe']:.2f} drop {v['dd']:.1f}% worst day {r[a:z].min()*100:.2f}% | v1 {base['val']['ret']:.1f}% {base['val']['sharpe']:.2f} {base['val']['dd']:.1f}%")
    if v["sharpe"] <= base["val"]["sharpe"]:
        print("  FAILED the 2020-22 gate. Final not run."); continue
    a, z = rng(s, "final"); r, t, e = run(a, z, A, p.cf, p.tr, p.re); r2, _, _ = run(a, z, A, p.cf, p.tr, p.re, bps=1.2); f, f2 = score(r[a:z]), score(r2[a:z]); ok = f["sharpe"] > base["final"]["sharpe"] and f["ret"] > base["final"]["ret"] and f2["ret"] > 0
    print(f"  2023-Oct 26: {f['ret']:.1f}%/yr Sharpe {f['sharpe']:.2f} drop {f['dd']:.1f}% worst day {r[a:z].min()*100:.2f}% 2x {f2['ret']:.1f}% | v1 {base['final']['ret']:.1f}% {base['final']['sharpe']:.2f} {base['final']['dd']:.1f}% -> {'PASS' if ok else 'FAIL'}")
if el.empty:
    print("\nNo variant beat v1 on 2016-2019, so no later data was run.")
