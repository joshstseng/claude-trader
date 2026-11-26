"""Aligned daily panel of every stock that was ever top-500 by dollar volume (active and delisted)."""
from __future__ import annotations
import gzip, json, pickle
from datetime import date
import numpy as np
from app.research import yahoo
from app.research.wheel.fetch import DAILY, DIR
END = date(2026, 10, 30)

class Panel: pass

def build():
    f = DIR / "panel.pkl"
    if f.exists(): return pickle.load(open(f, "rb"))
    days = [b.t.date() for b in yahoo.daily("SPY") if date(2015, 1, 2) <= b.t.date() <= END]
    ix = {d: i for i, d in enumerate(days)}
    names = sorted(p.name[:-8] for p in DAILY.glob("*.json.gz"))
    n, m = len(days), len(names)
    A = {k: np.full((n, m), np.nan, dtype=np.float32) for k in "ohlcv"}
    for j, s in enumerate(names):
        for t, o, h, l, c, v in json.load(gzip.open(DAILY / f"{s}.json.gz", "rt")):
            i = ix.get(date.fromisoformat(t))
            if i is not None and c > 0:
                A["o"][i, j], A["h"][i, j], A["l"][i, j], A["c"][i, j], A["v"][i, j] = o, h, l, c, v
    P = Panel(); P.days, P.names = days, names
    for k, v in A.items(): setattr(P, k, v)
    pickle.dump(P, open(f, "wb"), protocol=4)
    return P


BANKRUPT = set("""SIVB SIVBQ SBNY FRC FRCB BBBYQ JCP RAD WE BIG PRTY PRTYQ TUP NKLA FSR RIDE RIDEQ SAVE YELL YELLQ REV ENDP MNK FTR WIN GNC PIR
ASNA TLRD DO OAS GPOR AKRX EXPR BRDS CANO DBD AVYA UPL SN HK ULTR CRC NE VAL PACD SD CHK DNR WFT MULN ARVL FFIE""".split())
ACTIONS = {("AA", date(2016, 11, 1)), ("APTV", date(2017, 12, 5)), ("DLPH", date(2017, 12, 5)), ("EQT", date(2018, 11, 13)),
           ("NVS", date(2019, 4, 9)), ("RTX", date(2020, 4, 3)), ("IAC", date(2020, 7, 1)), ("PPLI", date(2020, 7, 1)),
           ("DB", date(2017, 3, 21)), ("UA", date(2016, 4, 8))}      # spin-offs and share-class splits, not real losses
STALE_END = {"SBNY": date(2023, 3, 10)}          # regulators closed it; later prints are not tradable


def clean(P=None):
    """Adds to the panel: split-consistent prices with spin-off artifacts removed, failure dates (loss to zero), raw
    share prices and the point-in-time liquidity rank."""
    import pandas as pd
    f = DIR / "clean.pkl"
    if f.exists(): return pickle.load(open(f, "rb"))
    P = P or build(); n, m = P.c.shape
    c, v = pd.DataFrame(P.c.astype(float)), pd.DataFrame(P.v.astype(float))
    ret = c.ffill(limit=3).pct_change(fill_method=None).to_numpy(copy=True)
    avg = v.rolling(20, min_periods=8).mean().shift(1).values
    with np.errstate(invalid="ignore", divide="ignore"):
        fake = (np.abs(ret) > .35) & (v.values < 2 * avg)
    P.fixed = int(np.nansum(fake)); ret[fake] = 0.0
    where = {d: i for i, d in enumerate(P.days)}; pos0 = {s: j for j, s in enumerate(P.names)}
    for s, d in ACTIONS:
        if s in pos0: ret[where[d], pos0[s]] = 0.0
    idx = np.full((n, m), np.nan); P.fail = {}
    for j, s in enumerate(P.names):
        ok = np.where(~np.isnan(P.c[:, j]))[0]
        if len(ok) == 0: continue
        a, z = ok[0], ok[-1]
        if s in STALE_END:
            z = min(z, max(i for i, d in enumerate(P.days) if d <= STALE_END[s]))
        r = np.nan_to_num(ret[a:z + 1, j]); r[0] = 0
        idx[a:z + 1, j] = float(P.c[a, j]) * np.cumprod(1 + r)
        y = P.c[max(a, z - 252):z + 1, j]
        if s in BANKRUPT and z < n - 5 and (s in STALE_END or P.c[z, j] / np.nanmax(y) < .6):
            P.fail[j] = z
    with np.errstate(invalid="ignore", divide="ignore"):
        k = idx / P.c
    P.O, P.H, P.L, P.C = P.o * k, P.h * k, P.l * k, idx
    M = json.load(gzip.open(DIR / "monthly.json.gz", "rt")); top = json.loads((DIR / "top500.json").read_text())
    pos = {s: j for j, s in enumerate(P.names)}
    P.rank = {mo: [pos[s] for s in x if s in pos] for mo, x in top.items()}
    P.raw = {s: {a: b for a, b, _ in M[s]} for s in P.names if s in M}
    del P.o, P.h, P.l, P.c
    pickle.dump(P, open(f, "wb"), protocol=4); return P
