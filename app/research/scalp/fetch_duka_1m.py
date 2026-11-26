"""Slow, single-connection download of Dukascopy 1-minute BID candles, one UTC day per file.
TLS verification stays on. Backs off on 429/5xx. Finished days are cached; re-running resumes.
Order: dev years first (2016-2019), then 2020-2022, then 2023-2026, so testing can start early."""
import gzip
import json
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SYMS = ["USDJPY", "AUDUSD", "EURUSD", "XAUUSD"]
OUT = Path("data/bars/lab/intraday/duka1m")
PAUSE = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
SPANS = [(date(2016, 1, 1), date(2019, 12, 31)), (date(2020, 1, 1), date(2022, 12, 31)), (date(2023, 1, 1), date(2026, 10, 31))]


def fetch(url):
    wait = 20
    for _ in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            if e.code not in (429, 500, 502, 503, 504):
                raise
            print(time.strftime("%H:%M:%S"), "backoff", e.code, wait, flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if "CERTIFICATE" in str(e).upper():
                raise
            print(time.strftime("%H:%M:%S"), "retry", type(e).__name__, wait, flush=True)
        time.sleep(wait); wait = min(wait * 2, 600)
    return None


got, miss, t0 = 0, [], time.time()
for a, z in SPANS:
    d = a
    while d <= z:
        if d.weekday() != 5:                                     # Saturday: forex and gold are closed
            for s in SYMS:
                f = OUT / s / f"{d:%Y}" / f"{d:%Y-%m-%d}.json.gz"
                if f.exists():
                    continue
                b = fetch(f"https://datafeed.dukascopy.com/datafeed/{s}/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5")
                time.sleep(PAUSE)
                if b is None:
                    miss.append(f"{s} {d}"); continue
                rows = []
                if b:
                    raw = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(b)
                    base = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
                    for i in range(len(raw) // 24):
                        t, o, c, lo, h, v = struct.unpack(">IIIIIf", raw[i * 24:(i + 1) * 24])
                        if v > 0:
                            rows.append([base + t, o, h, lo, c, round(v, 2)])
                f.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(f.with_suffix(".tmp"), "wt") as fh:
                    json.dump(rows, fh)
                f.with_suffix(".tmp").replace(f)
                got += 1
        if d.day == 1 or d == z:
            print(time.strftime("%H:%M:%S"), "through", d, "new files", got, f"{got / max(time.time() - t0, 1):.2f}/s",
                  "missing", len(miss), flush=True)
        d += timedelta(days=1)
    print(time.strftime("%H:%M:%S"), "SPAN DONE", a, z, flush=True)
print("ALL DONE missing", len(miss), miss[:20], flush=True)
