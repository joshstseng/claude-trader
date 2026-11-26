"""The live Swing rules must reproduce the research backtest, session by session, on real QQQ bars."""
import numpy as np

from app.research.swing.intraday import load, noise
from app.research.swing.v1x import bands, rng
from app.research.swing.x81_pd_audit import sim
from app.strategies.swing import BARS, Machine, context

s = load("QQQ"); U, D = bands(s); a, z = rng(s, "val")[0], rng(s, "final")[1]
v1 = noise(s, a, z, look=14, every=6, vm=1.0)[0]; v11 = sim(s, U, D, a, z)[0]
bad1 = bad2 = n = 0; worst = 0.0
for i in range(a, z):
    if not np.isfinite(s.vol[i]) or s.vol[i] <= 0 or not np.isfinite(s.prev[i]):
        continue
    ctx = context(s.o[:i], s.h[:i], s.l[:i], s.c[:i]); M1 = Machine.start(ctx, s.o[i, 0], False); M2 = Machine.start(ctx, s.o[i, 0], True)
    for b in range(BARS):
        M1.step(b, s.o[i], s.h[i], s.l[i], s.c[i]); M2.step(b, s.o[i], s.h[i], s.l[i], s.c[i])
    n += 1; d1, d2 = abs(M1.pnl - v1[i]), abs(M2.pnl - v11[i]); bad1 += d1 > 1e-6; bad2 += d2 > 1e-6; worst = max(worst, d1, d2)
print(f"sessions {n}; v1 mismatches {bad1}; v1.1 mismatches {bad2}; largest daily difference {worst*1e4:.4f} bp")
raise SystemExit(1 if bad1 or bad2 else 0)
