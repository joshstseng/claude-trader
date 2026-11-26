"""Swing v2: choose on 2016-2019, gate on 2020-2022, final once on 2023-Oct 2026, following FROZEN_V2.md."""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, noise, sharpe
from app.research.swing.v2lab import Spec, build, run, variants

W = {"dev": ("2016-01-01", "2019-12-31"), "val": ("2020-01-01", "2022-12-31"), "final": ("2023-01-01", "2026-10-31")}


def rng(T, w):
    return int(T.days.searchsorted(pd.Timestamp(W[w][0]))), int(T.days.searchsorted(pd.Timestamp(W[w][1]), side="right"))


def res(T, sp, w, mult=1.0):
    a, z = rng(T, w); x, t, sk = run(T, sp, a, z, mult=mult); x = x[a:z]; e = x.cumsum()
    return dict(ret=x.mean() * 252 * 100, sharpe=sharpe(x), dd=(e - np.maximum.accumulate(e)).min() * 100, trades=t, skipped=sk, x=x)


q = load("QQQ"); B = {s: build(s, base=q) for s in (1, 5)}; CTRL = Spec("now", 0, "skip")
for s, T in B.items():
    for w in W:
        a, z = rng(T, w); c = run(T, CTRL, a, z)[0][a:z]; o = pd.Series(noise(q, *(q.days.searchsorted(pd.Timestamp(W[w][0])), q.days.searchsorted(pd.Timestamp(W[w][1]), side="right")), look=14, every=6, vm=1.0)[0]).to_numpy()
        o = pd.Series(o, index=q.days).reindex(T.days[a:z]).to_numpy()
        print(f"control {s}m {w}: v2 engine with v1 entry {c.mean()*252*100:.2f}%/yr Sharpe {sharpe(c):.2f} | frozen v1 {o.mean()*252*100:.2f}%/yr Sharpe {sharpe(o):.2f} | corr {np.corrcoef(c,o)[0,1]:.4f}")
V1 = {w: res(B[5], CTRL, w) for w in W}
print("\nv1 on matching days:", {w: (round(v['ret'], 1), round(v['sharpe'], 2), round(v['dd'], 1), v['trades']) for w, v in V1.items()})
rows = []
for tf, T in B.items():
    for sp in variants():
        r, r2 = res(T, sp, "dev"), res(T, sp, "dev", 2.0)
        rows.append(dict(tf=tf, sp=sp, group=sp.group, name=f"{tf}m {sp.name}", ret=r["ret"], sharpe=r["sharpe"], sharpe2x=r2["sharpe"], ret2x=r2["ret"], dd=r["dd"], trades=r["trades"], skipped=r["skipped"]))
o = pd.DataFrame(rows); o.drop(columns="sp").to_pickle("data/bars/lab/intraday/x60.pkl")
print(f"\nDEV 2016-2019: {len(o)} variants. Beat v1 Sharpe: {(o.sharpe>V1['dev']['sharpe']).sum()}, profitable: {(o.ret>0).sum()}, median Sharpe {o.sharpe.median():.2f}")
print("median Sharpe by group / timeframe / wait fallback:"); print(o.groupby(["group", "tf"]).sharpe.median().unstack().round(2).to_string())
print("skip vs market fallback:", {k: round(o[o.name.str.endswith(k)].sharpe.median(), 2) for k in ("skip", "market")})
print("\nTop 12 on dev"); print(o.sort_values("sharpe", ascending=False).head(12)[["name", "ret", "sharpe", "sharpe2x", "dd", "trades", "skipped"]].round(2).to_string(index=False))
el = o[(o.sharpe > 1.03) & (o.sharpe > V1["dev"]["sharpe"]) & (o.ret2x > 0) & (o.trades >= 100)]
picks = [g.sort_values("sharpe", ascending=False).iloc[0] for _, g in el.groupby("group")]
print(f"\nEligible: {len(el)}. Frozen picks: {[p['name'] for p in picks]}")
for p in picks:
    T = B[p.tf]; sp = p.sp; v = res(T, sp, "val"); print(f"\n{p['name']}\n  VAL {v['ret']:.1f}%/yr Sharpe {v['sharpe']:.2f} DD {v['dd']:.1f}% trades {v['trades']} vs v1 {V1['val']['ret']:.1f}%/yr {V1['val']['sharpe']:.2f}")
    if v["sharpe"] <= V1["val"]["sharpe"]:
        print("  validate: FAIL. Final not run."); continue
    f, f2 = res(T, sp, "final"), res(T, sp, "final", 2.0); ok = f["sharpe"] > V1["final"]["sharpe"] and f["ret"] > V1["final"]["ret"] and f2["ret"] > 0
    print(f"  FINAL {f['ret']:.1f}%/yr Sharpe {f['sharpe']:.2f} DD {f['dd']:.1f}% trades {f['trades']} | 2x {f2['ret']:.1f}%/yr | v1 {V1['final']['ret']:.1f}%/yr {V1['final']['sharpe']:.2f} DD {V1['final']['dd']:.1f}% -> {'PASS' if ok else 'FAIL'}")
