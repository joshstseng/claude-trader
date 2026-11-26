"""Slow, single-connection download of Dukascopy hourly bid candles. TLS verification stays on; finished months are cached."""
import gzip
import json
import lzma
import struct
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SYMS = ["EURUSD", "USDJPY", "XAUUSD", "LIGHTCMDUSD", "USA500IDXUSD", "USATECHIDXUSD", "GBPUSD", "AUDUSD", "USDCAD"]
OUT = Path("data/bars/lab/intraday/duka")
PAUSE = 1.5


def fetch(url):
    wait = 30
    for _ in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if "CERTIFICATE" in str(e).upper():
                raise
        time.sleep(wait); wait = min(wait * 2, 300)
    return None


SYMS = ["EURUSD", "USDJPY", "XAUUSD", "LIGHTCMDUSD", "GBPUSD", "AUDUSD", "USDCAD"]  # forex, gold and oil; indexes are already covered
got, miss = 0, []
for y in range(2012, 2027):  # every market advances together, so a stop leaves equal coverage
    for m in range(12):  # Dukascopy months are zero-based
        if (y, m) > (2026, 9):
            continue
        for s in SYMS:
            f = OUT / s / f"{y}-{m + 1:02d}.json.gz"
            if f.exists():
                continue
            b = fetch(f"https://datafeed.dukascopy.com/datafeed/{s}/{y}/{m:02d}/BID_candles_hour_1.bi5")
            time.sleep(PAUSE)
            if b is None:
                miss.append(f"{s} {y}-{m + 1:02d}"); continue
            rows = []
            if b:
                raw = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(b)
                base = int(datetime(y, m + 1, 1, tzinfo=timezone.utc).timestamp())
                for i in range(len(raw) // 24):
                    t, o, c, l, h, v = struct.unpack(">IIIIIf", raw[i * 24:(i + 1) * 24])
                    if v > 0:
                        rows.append([base + t, o, h, l, c, round(v, 3)])
            f.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(f.with_suffix(".tmp"), "wt") as fh:
                json.dump(rows, fh)
            f.with_suffix(".tmp").replace(f)
            got += 1
    print(time.strftime("%H:%M"), "finished", y, m + 1, "new files", got, "missing", len(miss), flush=True) if False else None
    print(time.strftime("%H:%M"), "finished year", y, "new files", got, "missing", len(miss), flush=True)
print("ALL DONE missing", miss, flush=True)
