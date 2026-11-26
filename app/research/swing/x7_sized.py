"""Step 7: can a real account hold the trend sleeve in whole contracts? Pre-2019 only."""
import pandas as pd

from app.research.swing.lab import load, stats
from app.research.swing.sized import MULT, run

d = load(); cols = list(MULT); sp = d.ret["SP500"].fillna(0)
print(f"{'capital':>10}{'dev Sh':>8}{'val Sh':>8}{'val ret':>8}{'val DD':>8}{'avg open':>9}{'trades/yr':>10} | S&P+.5 trend dev Sh, val Sh, val ret")
for cap in (25000, 50000, 100000, 250000, 1000000):
    r, c = run(d, cap, cols)
    a, b = stats(r.loc["1985":"2012"]), stats(r.loc["2013":"2018"])
    o1, o2 = stats((sp + .5 * r).loc["1985":"2012"]), stats((sp + .5 * r).loc["2013":"2018"])
    print(f"{cap:>10,}{a['sharpe']:8.2f}{b['sharpe']:8.2f}{b['ret']*100:8.1f}{b['dd']*100:8.1f}{(c.loc['2013':'2018']!=0).sum(axis=1).mean():9.1f}{c.loc['2013':'2018'].diff().abs().sum().sum()/6:10.0f} | {o1['sharpe']:.2f}, {o2['sharpe']:.2f}, {o2['ret']*100:.1f}%")
print("reference S&P excess: dev", round(stats(sp.loc['1985':'2012'])['sharpe'], 2), "val", round(stats(sp.loc['2013':'2018'])['sharpe'], 2), "val ret", round(stats(sp.loc['2013':'2018'])['ret'] * 100, 1))
