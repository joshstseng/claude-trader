"""Download 5-minute split- and dividend-adjusted SIP bars from Alpaca, read-only market data."""
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SYMS = ["SPY", "QQQ", "IWM", "GLD", "SLV", "USO", "FXE", "FXY", "FXB", "FXA", "TLT"]
OUT = Path("data/bars/lab/intraday/alpaca"); OUT.mkdir(parents=True, exist_ok=True)
K = {}
for line in open(".env"):
    if "=" in line and not line.startswith("#"):
        a, b = line.strip().split("=", 1); K[a] = b.strip("\"'")
H = {"APCA-API-KEY-ID": K["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": K["ALPACA_SECRET_KEY"]}

for s in SYMS:
    f = OUT / f"{s}.json.gz"
    if f.exists():
        continue
    rows, token, pages = [], None, 0
    while True:
        q = {"timeframe": "5Min", "start": "2016-01-01T00:00:00Z", "end": "2026-11-01T00:00:00Z", "limit": 10000, "adjustment": "all", "feed": "sip"}
        if token:
            q["page_token"] = token
        for wait in (0, 10, 30, 60, 120):
            time.sleep(wait)
            try:
                with urllib.request.urlopen(urllib.request.Request(f"https://data.alpaca.markets/v2/stocks/{s}/bars?" + urllib.parse.urlencode(q), headers=H), timeout=60) as r:
                    j = json.load(r)
                break
            except (urllib.error.URLError, TimeoutError) as e:
                print(s, "retry", type(e).__name__, flush=True); j = None
        if j is None:
            raise SystemExit(f"failed on {s}")
        rows += [[b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in j.get("bars") or []]
        token = j.get("next_page_token"); pages += 1
        time.sleep(.35)
        if not token:
            break
    with gzip.open(f.with_suffix(".tmp"), "wt") as fh:
        json.dump(rows, fh)
    f.with_suffix(".tmp").replace(f)
    print("DONE", s, len(rows), rows[0][0], rows[-1][0], "pages", pages, flush=True)
print("ALL DONE", flush=True)
