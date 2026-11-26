"""Why pullback entries trail v1, and whether a half-and-half entry helps. DEV 2016-2019 only."""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, sharpe
from app.research.swing.v2lab import CHECKS, Spec, build, run, scan

q = load("QQQ"); T = build(1, base=q); a = int(T.days.searchsorted(pd.Timestamp("2016-01-01"))); z = int(T.days.searchsorted(pd.Timestamp("2019-12-31"), side="right"))
chks = [(k + 1) * 5 - 1 for k in CHECKS]
TESTS = {"touch band": Spec("lim", 15, "skip", level="band"), "RSI2<20": Spec("osc", 15, "skip", n=2, lvl=20), "touch EMA9": Spec("lim", 15, "skip", level="ema9")}
rows = []
for i in range(a, z):
    w = T.w[i]
    if w <= 0:
        continue
    side, en, ck0 = 0, 0., 0
    for j, ck in enumerate(chks):
        want = int(T.sig[i, j]); nx = ck + 1
        if side and want != side:
            rows.append((i, side, en, ck0, float(T.o[i, nx]), w)); side = 0
        if not side and want:
            side, en, ck0 = want, float(T.o[i, nx]), ck
    if side:
        rows.append((i, side, en, ck0, float(T.c[i, -1]), w))
R = pd.DataFrame(rows, columns=["i", "side", "en", "ck", "ex", "w"]); R["pnl"] = R.side * (R.ex / R.en - 1) * R.w - 2 * .6e-4 * R.w
print(f"v1 trades on dev: {len(R)}, total {R.pnl.sum()*100:.1f}%, average {R.pnl.mean()*1e4:.1f} bp")
for k, sp in TESTS.items():
    got, imp = [], []
    for r in R.itertuples():
        f = scan(T, r.i, r.side, r.ck + 1, min(r.ck + 15, 388), r.ck, sp); got.append(f is not None)
        imp.append(np.nan if f is None else r.side * (r.en / f[1] - 1) * 1e4)
    g = np.array(got); y, n = R.pnl[g], R.pnl[~g]
    print(f"{k:<12} pullback came on {g.mean():.0%} of trades. v1 average with pullback {y.mean()*1e4:6.1f} bp, without {n.mean()*1e4:6.1f} bp. Trades without one made {n.sum()/R.pnl.sum():.0%} of v1 profit. Average entry improvement {np.nanmean(imp):.1f} bp")
top = R.sort_values("pnl", ascending=False).head(20); print("\nTop 20 v1 winners:", f"{top.pnl.sum()/R.pnl.sum():.0%} of total profit")
v1 = run(T, Spec("now", 0, "skip"), a, z)[0][a:z]
print(f"\nHalf at breakout, half on pullback (v1 alone: {v1.mean()*252*100:.2f}%/yr, Sharpe {sharpe(v1):.2f})")
for k, sp in (("RSI2<20, 15m", Spec("osc", 15, "skip", n=2, lvl=20)), ("RSI2<20, 30m", Spec("osc", 30, "skip", n=2, lvl=20)), ("touch EMA9, 15m", Spec("lim", 15, "skip", level="ema9")), ("touch band, 15m", Spec("lim", 15, "skip", level="band")), ("reversal, 30m", Spec("rev", 30, "skip"))):
    x = run(T, sp, a, z)[0][a:z]; h = .5 * v1 + .5 * x; e = h.cumsum()
    print(f"  {k:<18}{h.mean()*252*100:6.2f}%/yr  Sharpe {sharpe(h):5.2f}  worst drop {(e-np.maximum.accumulate(e)).min()*100:6.1f}%  {'beats v1' if sharpe(h) > sharpe(v1) else 'does not beat v1'}")
