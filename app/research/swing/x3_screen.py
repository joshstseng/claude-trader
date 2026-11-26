"""Step 3: broad screen after trend + carry failed validation. Holdout (2019+) is never read here.

Every variant printed counts as a trial. A candidate must have net Sharpe >= 0.5 on BOTH dev (1985-2012) and
val (2013-2018), and the trial count is used later to discount the best result.
"""
import numpy as np
import pandas as pd

from app.research.swing.lab import GROUPS, carry, ewmac, load, simulate, stats, window

d = load()
d_cut = d.adj.index[d.adj.index <= "2018-12-31"]
ALL = list(d.adj.columns)
EQ, MET, EN, RT, FX, AG = (GROUPS[k] for k in ("equity", "metals", "energy", "rates", "fx", "ags"))
COM = MET + EN + AG
IDX = d.adj.index


def only(f, cols):
    return f[cols]


def rank_ls(x, cols, frac=1 / 3):
    r = x[cols].rank(axis=1, pct=True)
    n = x[cols].notna().sum(axis=1)
    o = (r > 1 - frac).astype(float) - (r <= frac).astype(float)
    return o.where(x[cols].notna()).where(n >= 6, 0.0)


def tom(before=1, after=3):
    s = pd.Series(IDX, index=IDX)
    mo = s.dt.to_period("M")
    pos = mo.groupby(mo).cumcount(); rev = mo[::-1].groupby(mo[::-1]).cumcount()[::-1]
    on = (pos < after) | (rev < before)
    return on.shift(-2).fillna(False).astype(float)  # known ahead: position is on during the window


def rsi(x, n=2):
    c = x.diff(); u = c.clip(lower=0).ewm(alpha=1 / n).mean(); v = (-c.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 * u / (u + v).replace(0, np.nan)


trend = pd.concat([ewmac(d, n) for n in (16, 32, 64)]).groupby(level=0).mean()
ma200 = d.adj.rolling(200, min_periods=200).mean()
up = (d.adj > ma200).astype(float).where(ma200.notna())
c = carry(d)
mom12 = d.adj.diff(252) / (d.vol * 16 * 16)
mom_skip = (d.adj.shift(21) - d.adj.shift(252)) / (d.vol * 16 * 16)
seas = pd.DataFrame(index=IDX, columns=ALL, dtype=float)
m = (d.ret.fillna(0) + 1).groupby(IDX.to_period("M")).prod() - 1
ms = pd.DataFrame({s: [m[s].where(m.index.month == p.month).loc[:p - 1].tail(120).dropna().tail(10).mean() if (m[s].where(m.index.month == p.month).loc[:p - 1].dropna().size >= 5) else np.nan for p in m.index] for s in ALL}, index=m.index)
seas = ms.reindex(IDX.to_period("M")).set_axis(IDX).shift(2)
rv = d.ret.ewm(span=20).std() * 16
rv_lt = d.ret.ewm(span=500, min_periods=250).std() * 16
vm = (rv_lt / rv).clip(0, 2)
T = tom()
tom_f = pd.DataFrame({s: T for s in ALL})
dip = ((rsi(d.adj) < 10).astype(float) * up)
dip_hold = dip.replace(0, np.nan).ffill(limit=3).fillna(0).where(up.notna())
dd20 = d.adj / d.adj.rolling(20).max() - 1

V = {}
for g, cols in (("all", ALL), ("equity", EQ), ("metals", MET), ("energy", EN), ("rates", RT), ("fx", FX), ("ags", AG)):
    V[f"trend L/S {g}"] = (trend, cols)
    V[f"trend long-only {g}"] = (trend.clip(lower=0), cols)
    V[f"carry {g}"] = (c, cols)
    V[f"trend when carry agrees {g}"] = (trend.where(np.sign(trend) == np.sign(c), 0.0), cols)
    V[f"buy&hold risk-wtd {g}"] = (pd.DataFrame(1.0, index=IDX, columns=ALL).where(d.vol.notna()), cols)
    V[f"vol-managed long {g}"] = (vm, cols)
    V[f"turn-of-month {g}"] = (tom_f.where(d.vol.notna()), cols)
    V[f"RSI2 dip in uptrend {g}"] = (dip_hold, cols)
    V[f"long above 200d {g}"] = (up, cols)
for g, cols in (("commods", COM), ("fx", FX), ("all", ALL)):
    V[f"xs momentum {g}"] = (rank_ls(mom_skip, cols), cols)
    V[f"xs carry {g}"] = (rank_ls(c, cols), cols)
    V[f"xs seasonality {g}"] = (rank_ls(seas, cols), cols)
    V[f"xs carry+mom {g}"] = (rank_ls(c.rank(axis=1, pct=True) + mom_skip.rank(axis=1, pct=True), cols), cols)

rows = []
for k, (f, cols) in V.items():
    cols = [x for x in cols if x in f]
    r = simulate(d, f.reindex(columns=cols), cols=cols, idm=1.5).loc[:"2018-12-31"]
    a, b = stats(r.loc["1985":"2012"].net), stats(r.loc["2013":"2018"].net)
    rows.append(dict(name=k, dev=a["sharpe"], val=b["sharpe"], dev_ret=a["ret"] * 100, val_ret=b["ret"] * 100, val_dd=b["dd"] * 100,
                     corr=r.loc["2013":"2018"].net.corr(d.ret["SP500"].loc["2013":"2018"])))
o = pd.DataFrame(rows).set_index("name")
o["worst"] = o[["dev", "val"]].min(axis=1)
o.to_pickle(d.adj.__class__ and "data/bars/lab/swing/x3.pkl")
print("trials:", len(o), " passed (Sharpe>=.5 both):", int((o.worst >= .5).sum()))
print(o.sort_values("worst", ascending=False).head(32).round(2).to_string())
