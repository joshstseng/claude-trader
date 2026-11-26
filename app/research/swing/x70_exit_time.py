"""Swing v1 exits and check timing, following FROZEN_V1X.md."""
import numpy as np

from app.research.swing.intraday import load, noise
from app.research.swing.v1x import X, bands, gates, rng, run, score, vwap

s = load("QQQ"); U, D, VW = (*bands(s), vwap(s))
for w in ("dev", "val", "final"):
    a, z = rng(s, w); m = run(s, X(), a, z, U, D, VW)[0][a:z]; o = noise(s, a, z, look=14, every=6, vm=1.0)[0][a:z]
    print(f"control {w}: days differing from frozen v1 = {(np.abs(m-o) > 1e-9).sum()}")
E = [("Tighter of band or VWAP", X(exit="tight"), {}), ("VWAP only", X(exit="vwap"), {}), ("Looser of band or VWAP", X(exit="loose"), {}), ("Opposite band only", X(exit="opposite"), {}), ("Hold to close", X(exit="close"), {})]
E += [(f"Trail {k:g}x daily vol", X(exit="trail", k=k), {}) for k in (.25, .5, .75, 1., 1.5)]
gates(s, "EXITS", E, U, D, VW)
T = [("15m checks", X(every=3, first=2), {}), ("60m checks from 10:30", X(every=12, first=11), {}), ("60m checks from 10:00", X(every=12, first=5), {})]
gates(s, "CHECK TIMING", T, U, D, VW)
print("\nLate-entry check, 2016-2019: average entry bar and result by interval")
for lab, x in (("15m", X(every=3, first=2)), ("30m v1", X()), ("60m 10:30", X(every=12, first=11)), ("60m 10:00", X(every=12, first=5))):
    a, z = rng(s, "dev"); r, t = run(s, x, a, z, U, D, VW); m = score(r[a:z]); print(f"  {lab:<11} trades {t:4d}, days active {(r[a:z] != 0).mean():.0%}, average per trade {r[a:z].sum()/t*1e4:5.1f} bp, {m['ret']:.1f}%/yr")
