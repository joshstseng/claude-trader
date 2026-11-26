"""Download QQQ 1-minute adjusted SIP bars from Alpaca, keep the regular session, and save a days x 390 matrix."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("data/bars/lab/intraday/alpaca/QQQ_1m.npz")
K = {}
for line in open(".env"):
    if "=" in line and not line.startswith("#"):
        a, b = line.strip().split("=", 1); K[a] = b.strip("\"'")
H = {"APCA-API-KEY-ID": K["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": K["ALPACA_SECRET_KEY"]}
T, O, Hi, L, C, V = [], [], [], [], [], []
token, pages = None, 0
while True:
    q = {"timeframe": "1Min", "start": "2016-01-01T00:00:00Z", "end": "2026-11-01T00:00:00Z", "limit": 10000, "adjustment": "all", "feed": "sip"}
    if token:
        q["page_token"] = token
    j = None
    for wait in (0, 10, 30, 60, 120):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request("https://data.alpaca.markets/v2/stocks/QQQ/bars?" + urllib.parse.urlencode(q), headers=H), timeout=60) as r:
                j = json.load(r)
            break
        except (urllib.error.URLError, TimeoutError) as e:
            print("retry", type(e).__name__, flush=True)
    if j is None:
        raise SystemExit("download failed")
    for b in j.get("bars") or []:
        T.append(b["t"]); O.append(b["o"]); Hi.append(b["h"]); L.append(b["l"]); C.append(b["c"]); V.append(b["v"])
    token = j.get("next_page_token"); pages += 1
    if pages % 25 == 0:
        print("pages", pages, T[-1], flush=True)
    time.sleep(.32)
    if not token:
        break
t = pd.to_datetime(pd.Series(T), utc=True).dt.tz_convert("America/New_York")
d = t.dt.tz_localize(None).dt.normalize(); k = (t.dt.hour * 60 + t.dt.minute - 570).to_numpy()
m = (k >= 0) & (k < 390)
days = pd.DatetimeIndex(sorted(d[m].unique())); pos = pd.Series(np.arange(len(days)), index=days); i = d[m].map(pos).to_numpy(); j2 = k[m]
A = {}
for n, x in (("o", O), ("h", Hi), ("l", L), ("c", C), ("v", V)):
    a = np.full((len(days), 390), np.nan, dtype=np.float32 if n == "v" else np.float64); a[i, j2] = np.asarray(x)[m]; A[n] = a
np.savez_compressed(OUT, days=days.values.astype("datetime64[D]").astype(str), **A)
print("DONE", len(days), days[0].date(), days[-1].date(), "pages", pages, flush=True)
