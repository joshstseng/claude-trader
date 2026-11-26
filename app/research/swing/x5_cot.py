"""Step 5: CFTC positioning signals, pre-2019 only. Reports are used only after they were public."""
import numpy as np
import pandas as pd

from app.research.swing.lab import GROUPS, ewmac, load, simulate, stats

CODES = {"SP500": ["13874A", "138741"], "NASDAQ": ["209742"], "DOW": ["124603"], "RUSSELL": ["239742"], "GOLD": ["088691"], "SILVER": ["084691"],
         "COPPER": ["085692"], "PLAT": ["076651"], "PALLAD": ["075651"], "CRUDE_W": ["067651"], "HEATOIL": ["022651"], "GASOILINE": ["111659"],
         "GAS_US": ["023651"], "US2": ["042601"], "US5": ["044601"], "US10": ["043602"], "US20": ["020601"], "EUR": ["099741"], "JPY": ["097741"],
         "GBP": ["096742"], "AUD": ["232741"], "CAD": ["090741"], "CHF": ["092741"], "NZD": ["112741"], "MXP": ["095741"], "CORN": ["002602"],
         "SOYBEAN": ["005602"], "WHEAT": ["001602"], "REDWHEAT": ["001612"], "SOYOIL": ["007601"], "SOYMEAL": ["026603"], "LIVECOW": ["057642"],
         "FEEDCOW": ["061641"], "LEANHOG": ["054642"]}
d = load(); a = pd.read_pickle("data/bars/lab/swing/cot/all.pkl")
dc, kc = "As of Date in Form YYYY-MM-DD", "CFTC Contract Market Code"
a[kc] = a[kc].astype(str).str.strip()
H, S, N = {}, {}, {}
for s, cs in CODES.items():
    x = pd.concat([a[a[kc] == c] for c in cs]).drop_duplicates(dc).set_index(dc).sort_index()  # first code wins on overlap
    oi = x["Open Interest (All)"].astype(float).replace(0, np.nan)
    def f(l, r): return (x[l].astype(float) - x[r].astype(float)) / oi
    def pub(z):
        lag = np.where(z.index < "2000-01-01", 10, 3)  # conservative release lag
        z = z.copy(); z.index = z.index + pd.to_timedelta(lag, "D"); z = z[~z.index.duplicated(keep="last")]
        return z.reindex(d.adj.index.union(z.index)).ffill(limit=12).reindex(d.adj.index)
    H[s] = pub(f("Commercial Positions-Long (All)", "Commercial Positions-Short (All)"))
    S[s] = pub(f("Noncommercial Positions-Long (All)", "Noncommercial Positions-Short (All)"))
    N[s] = pub(f("Nonreportable Positions-Long (All)", "Nonreportable Positions-Short (All)"))
H, S, N = (pd.DataFrame(v) for v in (H, S, N))
cols = list(H.columns)


def z(x, n=780):
    return ((x - x.rolling(n, min_periods=n // 2).mean()) / x.rolling(n, min_periods=n // 2).std()).clip(-3, 3)


def rank_ls(x, cc, frac=1 / 3):
    r = x[cc].rank(axis=1, pct=True); n = x[cc].notna().sum(axis=1)
    return ((r > 1 - frac).astype(float) - (r <= frac).astype(float)).where(x[cc].notna()).where(n >= 6, 0.0)


trend = pd.concat([ewmac(d, n) for n in (16, 32, 64)]).groupby(level=0).mean()[cols]
zh, zs, zn = z(H), z(S), z(N)
dS = z(S - S.shift(20), 780)
V = {}
SETS = {"all": cols, **{g: [s for s in v if s in cols] for g, v in GROUPS.items()}}
SETS["commods"] = SETS["metals"] + SETS["energy"] + SETS["ags"]
for g, cc in SETS.items():
    V[f"follow hedgers {g}"] = (zh / 1.5, cc)
    V[f"follow specs {g}"] = (zs / 1.5, cc)
    V[f"fade small traders {g}"] = (-zn / 1.5, cc)
    V[f"hedger extreme |z|>1.5 {g}"] = (np.sign(zh).where(zh.abs() > 1.5, 0.0).where(zh.notna()), cc)
    V[f"spec crowding fade |z|>1.5 {g}"] = (-np.sign(zs).where(zs.abs() > 1.5, 0.0).where(zs.notna()), cc)
    V[f"spec flow 4w {g}"] = (dS / 1.5, cc)
    V[f"trend + hedgers agree {g}"] = (trend[cc].where(np.sign(trend[cc]) == np.sign(zh[cc]), 0.0), cc)
    V[f"trend, skip spec-crowded {g}"] = (trend[cc].where(~((np.sign(trend[cc]) == np.sign(zs[cc])) & (zs[cc].abs() > 1.5)), 0.0), cc)
    if len(cc) >= 8:
        V[f"xs hedging pressure {g}"] = (rank_ls(H - H.rolling(260, min_periods=130).mean(), cc), cc)
        V[f"xs small-trader fade {g}"] = (rank_ls(-(N - N.rolling(260, min_periods=130).mean()), cc), cc)
rows = []
for k, (f, cc) in V.items():
    r = simulate(d, f.reindex(columns=cc), cols=cc, idm=1.5).loc[:"2018-12-31"]
    x, y = stats(r.loc["1990":"2012"].net), stats(r.loc["2013":"2018"].net)
    rows.append(dict(name=k, dev=x["sharpe"], val=y["sharpe"], dev_ret=x["ret"] * 100, val_ret=y["ret"] * 100, val_dd=y["dd"] * 100,
                     corr=r.loc["2013":"2018"].net.corr(d.ret["SP500"].loc["2013":"2018"])))
o = pd.DataFrame(rows).set_index("name"); o["worst"] = o[["dev", "val"]].min(axis=1)
print("trials:", len(o), "passed (Sharpe>=.5 both):", int((o.worst >= .5).sum()))
print(o.sort_values("worst", ascending=False).head(22).round(2).to_string())
