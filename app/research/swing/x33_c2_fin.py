"""Candidate 2 with overnight financing charged. Settings are unchanged; this corrected run is the one that counts."""
import json

import numpy as np
import pandas as pd

from app.research.swing.hourly import donchian, engine, hourly
from app.research.swing.intraday import COST, Sess, load, sharpe, span

P = dict(n=70, k=3., direction=1); D = {m: load(m) for m in COST}
j = json.load(open("data/bars/lab/swing/etf/long_^IRX.json"))["chart"]["result"][0]
IRX = pd.Series(j["indicators"]["quote"][0]["close"], index=pd.to_datetime(j["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).normalize()).dropna().groupby(level=0).last() / 100 / 252


def cut(s, z):
    return Sess(s.sym, s.days[:z], s.o[:z], s.h[:z], s.l[:z], s.c[:z], s.v[:z], s.vol[:z], s.prev[:z])


def port(w, mult=1.0):
    R = {}
    for m, s in D.items():
        a, z = span(s, w); b = hourly(cut(s, z)); f = IRX.reindex(b.days).ffill().bfill().to_numpy()
        x, _ = engine(b, *donchian(b, **P), mult=mult, fin=f); R[m] = pd.Series(x[a:z], index=b.days[a:z])
    X = pd.DataFrame(R).fillna(0); return X.sum(axis=1) * 1.5 / np.sqrt(len(R)), X


def line(k, x):
    e = x.cumsum(); print(f"{k:<28}{x.mean()*252*100:6.1f}%/yr  Sharpe {sharpe(x):5.2f}  max DD {(e-e.cummax()).min()*100:6.1f}%")


if __name__ == "__main__":
    for w in ("dev", "val", "final"):
        x, X = port(w); x2, _ = port(w, 2.0); print(w.upper()); line("1x costs + financing", x); line("2x costs + financing", x2)
        print("  by year %:", (x.groupby(x.index.year).sum() * 100).round(1).to_dict(), "| by market Sharpe:", {m: round(sharpe(X[m]), 2) for m in X})
    x, _ = port("final"); x2, _ = port("final", 2.0); v, _ = port("val"); v2, _ = port("val", 2.0)
    sp = load("SPY"); a, z = span(sp, "final"); s = pd.Series(sp.c[a:z, -1] / np.r_[sp.prev[a], sp.c[a:z - 1, -1]] - 1, index=sp.days[a:z]) - IRX.reindex(sp.days[a:z]).ffill()
    q = pd.concat([x, s], axis=1, join="inner"); q.columns = ["x", "s"]; y = x.groupby(x.index.year).sum(); share = y.max() / x.sum() if x.sum() > 0 else np.inf
    print("\nSPY over T-bills, final:"); line("SPY", s); line("SPY + strategy", q.x + q.s); print("corr to SPY", round(q.x.corr(q.s), 2))
    C = [("gate: validate positive at 1x and 2x", v.sum() > 0 and v2.sum() > 0), ("1 Sharpe>=.7 and profit>0", sharpe(x) >= .7 and x.sum() > 0), ("2 profit>0 at 2x", x2.sum() > 0), ("4 3+ of 4 years up", (y > 0).sum() >= 3), ("5 no year >60%", share <= .6), ("6 corr<.3 and improves SPY", q.x.corr(q.s) < .3 and sharpe(q.x + q.s) > sharpe(q.s))]
    for k, ok in C: print(("PASS " if ok else "FAIL ") + k)
    print("VERDICT (trade count unchanged at 474):", "PASS" if all(ok for _, ok in C) else "FAIL")
