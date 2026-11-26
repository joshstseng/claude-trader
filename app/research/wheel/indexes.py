"""Layer A: Cboe's published option-selling indexes (real option prices) against the S&P 500 total return."""
from __future__ import annotations
import csv, io, math, urllib.request
from datetime import date, datetime
from app.research.data import LAB
from app.research import yahoo
DIR = LAB / "wheel"
NAMES = {"PUT": "Sell monthly at-the-money S&P puts", "WPUT": "Sell weekly at-the-money S&P puts",
         "BXM": "Buy S&P, sell monthly at-the-money calls", "BXMD": "Buy S&P, sell monthly 30-delta calls",
         "CNDR": "Monthly iron condor", "PPUT": "Buy S&P plus 5% protective puts"}

def cboe(sym):
    f = DIR / f"cboe_{sym}.csv"
    if not f.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        r = urllib.request.Request(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv", headers={"User-Agent": "Mozilla/5.0"})
        f.write_bytes(urllib.request.urlopen(r, timeout=30).read())
    out = {}
    for row in csv.DictReader(io.StringIO(f.read_text())):
        try:
            v = float(row[sym])
            if v > 0: out[datetime.strptime(row["DATE"], "%m/%d/%Y").date()] = v
        except (ValueError, KeyError): pass
    return out

def yh(sym, start=date(1988, 1, 1)):
    return {b.t.date(): b.c for b in yahoo.daily(sym, start=start)}

def stats(dates, eq, rf=None):
    n = len(eq) - 1
    yrs = (dates[-1] - dates[0]).days / 365.25
    r = [eq[i + 1] / eq[i] - 1 for i in range(n)]
    x = [a - (rf[i] if rf else 0) for i, a in enumerate(r)]
    m = sum(x) / n; sd = (sum((v - m) ** 2 for v in x) / n) ** .5
    pk = eq[0]; dd = 0
    for v in eq: pk = max(pk, v); dd = min(dd, v / pk - 1)
    return {"cagr": (eq[-1] / eq[0]) ** (1 / yrs) - 1, "dd": dd, "sharpe": m / sd * math.sqrt(252) if sd else 0, "vol": sd * math.sqrt(252)}
