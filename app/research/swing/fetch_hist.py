"""Slowly download free HistData 1-minute bars for forex, gold, oil and US indexes. Already-cached files are skipped."""
import gzip
import json
import sys
import time
from datetime import date

from app.backtest import histdata as h

PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "XAUUSD", "WTIUSD", "BCOUSD", "SPXUSD", "NSXUSD"]
START, END = date(2012, 1, 1), date(2026, 10, 31)

for pair in PAIRS:
    got, bad = 0, []
    for p in h.periods(START, END):
        f = h.cache_file(p.replace("/", "-"), pair)
        if f.exists():
            continue
        rows = None
        for wait in (0, 15, 60):
            time.sleep(wait)
            try:
                rows = h.fetch_period(p, pair)
                if rows:
                    break
            except Exception as e:
                print(pair, p, "retry after", type(e).__name__, flush=True)
        if not rows:
            bad.append(p)  # nothing is cached, so a failed period can be fetched again later
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        with gzip.open(tmp, "wt") as fh:
            json.dump(rows, fh)
        tmp.replace(f)
        got += 1
        print(pair, p, f"{len(rows):,}", flush=True)
        time.sleep(2)
    print("DONE", pair, "new", got, "missing", bad, flush=True)
print("ALL DONE", flush=True)
sys.exit(0)
