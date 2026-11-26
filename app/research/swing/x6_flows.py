"""Step 6: forced-flow and relative-value ideas, plus trend as an overlay on equities. Pre-2019 only."""
import numpy as np
import pandas as pd

from app.research.swing.lab import GROUPS, carry, ewmac, load, simulate, stats

d = load(); I = d.adj.index; ALL = list(d.adj.columns)
s = pd.Series(I, index=I); mo = s.dt.to_period("M")
pos = mo.groupby(mo).cumcount(); rev = mo[::-1].groupby(mo[::-1]).cumcount()[::-1]
V = {}


def rebalance(eq, bd, lastn):
    a, b = d.adj[eq], d.adj[bd]
    ra = (d.ret[eq].fillna(0)).groupby(mo).cumsum(); rb = (d.ret[bd].fillna(0)).groupby(mo).cumsum()
    x = (ra / (d.ret[eq].rolling(60).std() * 4.5) - rb / (d.ret[bd].rolling(60).std() * 4.5))
    win = rev.shift(-2).fillna(99) < lastn  # calendar known ahead; signal read two sessions before the earning day
    sig = -np.sign(x).where(win, 0.0)
    return pd.DataFrame({eq: sig, bd: -sig}).where(d.vol[[eq, bd]].notna())


for e in ("SP500", "NASDAQ"):
    for b in ("US10", "US5", "US20"):
        for n in (3, 5, 8):
            V[f"month-end rebalance {e}/{b} last{n}"] = (rebalance(e, b, n), [e, b])
PAIRS = [("GOLD", "SILVER"), ("GOLD", "PLAT"), ("SILVER", "COPPER"), ("CRUDE_W", "HEATOIL"), ("CRUDE_W", "GASOILINE"), ("HEATOIL", "GASOILINE"),
         ("CORN", "WHEAT"), ("WHEAT", "REDWHEAT"), ("SOYBEAN", "SOYMEAL"), ("SOYBEAN", "SOYOIL"), ("SOYBEAN", "CORN"), ("LIVECOW", "FEEDCOW"),
         ("LIVECOW", "LEANHOG"), ("US2", "US5"), ("US5", "US10"), ("US10", "US20"), ("SP500", "NASDAQ"), ("SP500", "RUSSELL"), ("SP500", "SP400"), ("SP500", "DOW"),
         ("EUR", "CHF"), ("EUR", "GBP"), ("AUD", "NZD"), ("AUD", "CAD")]
ret_v = d.ret / d.ret.ewm(span=32, min_periods=32).std()
for a, b in PAIRS:
    sp = (ret_v[a].fillna(0) - ret_v[b].fillna(0)).cumsum().where(d.vol[a].notna() & d.vol[b].notna())
    for n in (10, 20, 60):
        zz = ((sp - sp.rolling(n * 4).mean()) / sp.rolling(n * 4).std()).clip(-3, 3)
        sig = (-zz / 1.5).clip(-2, 2)
        V[f"pair revert {a}/{b} {n}"] = (pd.DataFrame({a: sig, b: -sig}), [a, b])
        V[f"pair trend {a}/{b} {n}"] = (pd.DataFrame({a: -sig, b: sig}), [a, b])
rows = []
for k, (f, c) in V.items():
    r = simulate(d, f.reindex(columns=c), cols=c, idm=1.0).loc[:"2018-12-31"]
    x, y = stats(r.loc["1990":"2012"].net), stats(r.loc["2013":"2018"].net)
    rows.append(dict(name=k, dev=x["sharpe"], val=y["sharpe"], dev_ret=x["ret"] * 100, val_ret=y["ret"] * 100, val_dd=y["dd"] * 100))
o = pd.DataFrame(rows).set_index("name"); o["worst"] = o[["dev", "val"]].min(axis=1)
print("trials:", len(o), "passed (Sharpe>=.5 both):", int((o.worst >= .5).sum()))
print(o.sort_values("worst", ascending=False).head(14).round(2).to_string())

print("\nOverlay: S&P futures + diversified trend at a fixed risk share (excess of cash)")
t = pd.concat([ewmac(d, n) for n in (16, 32, 64)]).groupby(level=0).mean()
tr = simulate(d, t, target=.15, idm=2.0).net
sp = d.ret["SP500"].fillna(0)
print(f"{'':<26}{'dev Sh':>8}{'dev DD':>8}{'val Sh':>8}{'val DD':>8}{'val ret':>9}")
for w in (0, .25, .5, .75, 1.0):
    x = sp + w * tr
    a, b = stats(x.loc["1985":"2012"]), stats(x.loc["2013":"2018"])
    print(f"S&P + {w:.2f} x trend      {a['sharpe']:8.2f}{a['dd']*100:8.1f}{b['sharpe']:8.2f}{b['dd']*100:8.1f}{b['ret']*100:9.1f}")
print("trend sleeve corr to S&P on S&P's 5% worst days (dev+val):", round(tr.loc['1985':'2018'][sp.loc['1985':'2018'] < sp.loc['1985':'2018'].quantile(.05)].mean() * 100, 3), "% avg trend return those days")
