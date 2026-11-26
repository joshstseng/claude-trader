"""Information only: does the pullback timing add anything over entering anywhere in Swing's direction?
Control = every 5-minute close while Swing v1 is long (short), same stop, min risk, 3R target, 3 a day."""
import numpy as np, pandas as pd
from app.research.scalp import lab as S
d = S.load(); side = np.load("data/bars/lab/intraday/scalp_swing_side.npy")
ep = S.filtered(S.ema_signals(d, "5m", "swing"), side)
L, Sh, sl, ss, xl, xs = ep
any5 = np.zeros_like(L); any5[:, 4::5] = True
ctrl = (any5 & (side > 0), any5 & (side < 0), sl, ss, xl, xs)
rng = np.random.default_rng(7)
for name, sig in (("EP5 pullback", ep), ("control: any 5m close in Swing direction", ctrl)):
    for w, (a, z) in S.WINDOWS.items():
        rows = np.flatnonzero((d.days.year >= int(a)) & (d.days.year <= int(z)))
        m = S.stats(d, S.simulate(d, sig, 3, rows=rows, min_risk=.0015), (a, z))
        print(f"{name:42} {w:5} trades {m['trades']:4} avg {m['avg_r']:+.3f}R pf {m['pf']:.2f} sharpe {m['sharpe']:.2f}")
# random subsets of the control with the same trade count as EP5 (final window), 200 draws
rows = np.flatnonzero(d.days.year >= 2023)
target = S.stats(d, S.simulate(d, ep, 3, rows=rows, min_risk=.0015), ("2023", "2026"))
res = []
for _ in range(200):
    keep = rng.random(L.shape) < .12
    sig = (ctrl[0] & keep, ctrl[1] & keep, sl, ss, xl, xs)
    res.append(S.stats(d, S.simulate(d, sig, 3, rows=rows, min_risk=.0015), ("2023", "2026"))["avg_r"])
res = np.array(res)
print(f"final window: EP5 {target['avg_r']:+.3f}R vs random Swing-direction entries median {np.median(res):+.3f}R, EP5 beats {np.mean(res < target['avg_r']):.0%} of 200 random draws")
