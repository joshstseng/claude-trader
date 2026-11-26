"""Layer B: real implied volatility from real option trades, and a model of it fitted on 2024 and checked on later data."""
from __future__ import annotations
import gzip, json, pickle
from datetime import date
import numpy as np, pandas as pd
from app.research.wheel import bs
from app.research.wheel.fetch import DIR
from app.research.wheel.indexes import yh
from app.research.wheel.panel import clean
OPT = DIR / "opt"

def features(P):
    r = pd.DataFrame(P.C).pct_change(fill_method=None)
    rv20 = r.rolling(20, min_periods=15).std().values * 252 ** .5; rv60 = r.rolling(60, min_periods=40).std().values * 252 ** .5
    return np.clip(rv20, .05, 6), np.clip(rv60, .05, 6)

def macro(days):
    V, I = yh("%5EVIX"), yh("%5EIRX"); vx, rf = [], []; a, b = 20., 3.
    for d in days: a = V.get(d, a); b = I.get(d, b); vx.append(a); rf.append(max(b, 0) / 100)
    return np.array(vx), np.array(rf)

def samples():
    f = DIR / "iv_samples.pkl"
    if f.exists(): return pickle.load(open(f, "rb"))
    P = clean(); pos = {s: j for j, s in enumerate(P.names)}; ix = {d: i for i, d in enumerate(P.days)}
    rv20, rv60 = features(P); vix, rf = macro(P.days); R = json.load(gzip.open(DIR / "raw2024.json.gz", "rt"))
    raw = {s: {date.fromisoformat(b[0]): b[4] for b in v} for s, v in R.items()}
    rows = []
    for fn in sorted(OPT.glob("*.json.gz")):
        doc = json.load(gzip.open(fn, "rt"))
        for k, bars in doc["bars"].items():
            m = doc["meta"][k]; u = m["u"]; j = pos.get(u)
            if j is None or u not in raw: continue
            exp = date.fromisoformat(m["exp"])
            for b in bars:
                d = date.fromisoformat(b[0]); i = ix.get(d); S = raw[u].get(d); dte = (exp - d).days
                if i is None or S is None or not 14 <= dte <= 55 or b[5] < 5 or np.isnan(rv20[i, j]) or np.isnan(rv60[i, j]): continue
                put = m["type"] == "put"
                if put and m["K"] >= S or not put and m["K"] <= S: continue
                rows.append((j, i, put, S, m["K"], dte / 365, b[4], b[5], rv20[i, j], rv60[i, j], vix[i], rf[i]))
    a = np.array(rows, dtype=float); out = []
    for put in (1., 0.):
        x = a[a[:, 2] == put]
        iv = bs.implied(x[:, 6], x[:, 3], x[:, 4], x[:, 5], x[:, 11], bool(put)); out.append(np.column_stack([x, iv]))
    A = np.vstack(out); A = A[~np.isnan(A[:, 12])]; pickle.dump(A, open(f, "wb"), protocol=4); return A

def X(rv20, rv60, vix, m, T, put):
    z = np.log(np.maximum(m, 1e-6)) / np.sqrt(T)          # log moneyness per root-year
    return np.column_stack([np.ones_like(z), np.log(rv20), np.log(rv60), np.log(vix / 20), z, z * z, np.log(T / .1), put, put * z])

def fit(A, mask):
    x = X(A[mask, 8], A[mask, 9], A[mask, 10], A[mask, 4] / A[mask, 3], A[mask, 5], A[mask, 2]); y = np.log(A[mask, 12])
    return np.linalg.lstsq(x, y, rcond=None)[0]

def predict(b, rv20, rv60, vix, m, T, put):
    return np.exp(X(np.atleast_1d(rv20), np.atleast_1d(rv60), np.atleast_1d(vix), np.atleast_1d(m), np.atleast_1d(T), np.atleast_1d(float(put))) @ b)


def fit_final():
    f = DIR / "iv_beta.pkl"
    if f.exists(): return pickle.load(open(f, "rb"))
    A = samples(); b = fit(A, trade_zone(A)); pickle.dump(b, open(f, "wb")); return b


def trade_zone(A):
    """Fit where the wheel actually trades: 10 to 45 delta."""
    d = np.empty(len(A))
    for put in (1., 0.):
        m = A[:, 2] == put
        d[m] = np.abs(bs.delta(A[m, 3], A[m, 4], A[m, 5], A[m, 11], A[m, 12], bool(put)))
    return (d >= .10) & (d <= .45)
