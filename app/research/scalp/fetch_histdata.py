"""Download HistData free 1-minute ASCII bars (EST, no DST) for the Asia research: years 2016-2025, months of 2026.
One request at a time with a pause; TLS verification on; finished files are skipped. Files go to their own folder."""
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path("data/bars/lab/intraday/histdata/raw")
PAIRS = ["USDJPY", "AUDUSD", "EURUSD", "XAUUSD"]
UA = {"User-Agent": "Mozilla/5.0"}


def get(url, data=None, ref=None):
    h = dict(UA)
    if ref:
        h["Referer"] = ref
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


jobs = [(p, str(y), None) for y in range(2016, 2026) for p in PAIRS] + [(p, "2026", m) for m in range(1, 11) for p in PAIRS]
for pair, year, month in jobs:
    name = f"{pair}_{year}" + (f"{month:02d}" if month else "") + ".zip"
    f = OUT / name
    if f.exists() and f.stat().st_size > 1000:
        continue
    page = f"https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair.lower()}/{year}" + (f"/{month}" if month else "")
    html = get(page).decode("utf-8", "replace")
    form = dict(re.findall(r'<input type="hidden" name="(\w+)" id="\w+" value="([^"]*)"', html))
    if "tk" not in form:
        print("no form for", name, flush=True); time.sleep(5); continue
    body = get("https://www.histdata.com/get.php", form, ref=page)
    if body[:2] != b"PK":
        print("not a zip for", name, len(body), flush=True); time.sleep(5); continue
    f.write_bytes(body)
    print(time.strftime("%H:%M:%S"), name, f"{len(body) / 1e6:.1f} MB", flush=True)
    time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 3)
print("ALL DONE", flush=True)
