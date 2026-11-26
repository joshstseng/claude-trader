"""Step 1: compare swing families on the DEV window only (through 2012)."""
import numpy as np
import pandas as pd

from app.research.swing.lab import breakout, carry, ewmac, load, reversal, simulate, stats, tsmom, window

d = load()
print("cost check, points per side:", d.cost.round(4).to_dict())
print("missing costs:", d.cost[d.cost.isna()].index.tolist())
F = {
    "tsmom 12m": tsmom(d),
    "ewmac 8": ewmac(d, 8), "ewmac 16": ewmac(d, 16), "ewmac 32": ewmac(d, 32), "ewmac 64": ewmac(d, 64),
    "breakout 20": breakout(d, 20), "breakout 40": breakout(d, 40), "breakout 80": breakout(d, 80), "breakout 160": breakout(d, 160),
    "carry": carry(d),
    "reversal 3d": reversal(d, 3), "reversal 5d": reversal(d, 5), "reversal 10d": reversal(d, 10),
}
F["trend blend"] = pd.concat([F[k] for k in ("ewmac 16", "ewmac 32", "ewmac 64")]).groupby(level=0).mean()
F["trend+carry"] = (F["trend blend"] * .6).add(F["carry"] * .4, fill_value=0).where(F["trend blend"].notna())
spx = window(d.ret["SP500"], "dev")
print(f"\nDEV through 2012 | {'family':<14}{'net%':>7}{'vol%':>6}{'Sharpe':>8}{'gross Sh':>9}{'DD%':>7}{'t':>6}{'cost%/y':>8}{'corr SPX':>9}")
for k, f in F.items():
    r = window(simulate(d, f), "dev").loc["1985":]
    s, g = stats(r.net), stats(r.gross)
    print(f"{k:<26}{s['ret']*100:7.1f}{s['vol']*100:6.1f}{s['sharpe']:8.2f}{g['sharpe']:9.2f}{s['dd']*100:7.1f}{s['t']:6.1f}{r.cost.mean()*256*100:8.2f}{r.net.corr(spx):9.2f}")
