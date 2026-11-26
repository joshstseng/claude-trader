"""Layer B: real expired option contracts and their daily traded bars, from Alpaca (January 2024 onward).
For each month: the 150 most liquid stocks known at the prior month-end, puts and calls for the next monthly expiry."""
from __future__ import annotations
import calendar, gzip, json, sys, urllib.parse
from datetime import date, timedelta
from app.research.wheel.fetch import DIR, _get, _hdr, bars
OPT = DIR / "opt"; RAW = DIR / "raw2024.json.gz"

def third_friday(y, m):
    d = date(y, m, 1); d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(days=14)

def cycles():
    out = []; y, m = 2024, 2
    while (y, m) <= (2026, 9):
        ny, nm = (y + (m == 12), 1 if m == 12 else m + 1)
        p = (y - (m == 1), 12 if m == 1 else m - 1)
        out.append({"entry_month": f"{y}-{m:02d}", "rank_month": f"{p[0]}-{p[1]:02d}", "exp": third_friday(ny, nm)})
        y, m = ny, nm
    return out

def contracts(us, exp, hdr):
    out, tok = [], None
    while True:
        q = {"underlying_symbols": ",".join(us), "expiration_date_gte": (exp - timedelta(days=1)).isoformat(),
             "expiration_date_lte": exp.isoformat(), "status": "inactive", "limit": 10000}
        if tok: q["page_token"] = tok
        d = _get("https://paper-api.alpaca.markets/v2/options/contracts?" + urllib.parse.urlencode(q), hdr)
        out += d.get("option_contracts") or []
        tok = d.get("next_page_token")
        if not tok: return out

def opt_bars(syms, start, end, hdr):
    out, tok = {}, None
    while True:
        q = {"symbols": ",".join(syms), "timeframe": "1Day", "start": start, "end": end, "limit": 10000, "sort": "asc"}
        if tok: q["page_token"] = tok
        d = _get("https://data.alpaca.markets/v1beta1/options/bars?" + urllib.parse.urlencode(q), hdr)
        for s, v in (d.get("bars") or {}).items():
            out.setdefault(s, []).extend([x["t"][:10], x["o"], x["h"], x["l"], x["c"], x["v"], x.get("n", 0)] for x in v)
        tok = d.get("next_page_token")
        if not tok: return out

def main():
    hdr = _hdr(); top = json.loads((DIR / "top500.json").read_text()); C = cycles()
    uni = {c["entry_month"]: top[c["rank_month"]][:150] for c in C if c["rank_month"] in top}; every = sorted({s for v in uni.values() for s in v})
    print("cycles", len(uni), "names", len(every), flush=True)
    if RAW.exists(): R = json.load(gzip.open(RAW, "rt"))
    else:
        R = {}
        for i in range(0, len(every), 60):
            for s, v in bars(every[i:i + 60], "1Day", "raw", hdr, start="2023-12-01").items():
                if v: R[s] = v
        json.dump(R, gzip.open(RAW, "wt"))
    OPT.mkdir(parents=True, exist_ok=True)
    for c in C:
        em = c["entry_month"]; f = OPT / f"{em}.json.gz"
        if f.exists() or em not in uni: continue
        spot = {}
        for s in uni[em]:
            x = [b for b in R.get(s, []) if b[0][:7] == em]
            if x: spot[s] = x[0][4]
        keep, meta = [], {}
        names = sorted(spot)
        for i in range(0, len(names), 40):
            for k in contracts(names[i:i + 40], c["exp"], hdr):
                u = k["underlying_symbol"]
                if u not in spot or k.get("size") not in ("100", 100) or not k["symbol"].startswith(u): continue
                K = float(k["strike_price"]); m = K / spot[u]
                if k["type"] == "put" and .70 <= m <= 1.02 or k["type"] == "call" and .98 <= m <= 1.30:
                    meta[k["symbol"]] = {"u": u, "type": k["type"], "K": K, "exp": k["expiration_date"]}
        by = {}
        for s, x in meta.items(): by.setdefault((x["u"], x["type"]), []).append(s)
        for (u, ty), v in by.items():
            aim = .88 if ty == "put" else 1.10
            keep += sorted(v, key=lambda s: abs(meta[s]["K"] / spot[u] - aim))[:16]
        B = {}
        start = f"{em}-01"; end = (c["exp"] + timedelta(days=1)).isoformat()
        for i in range(0, len(keep), 100):
            B.update(opt_bars(keep[i:i + 100], start, end, hdr))
        with gzip.open(f, "wt") as h: json.dump({"exp": c["exp"].isoformat(), "spot": spot, "meta": {s: meta[s] for s in keep}, "bars": B}, h)
        print(em, "exp", c["exp"], "names", len(spot), "contracts", len(keep), "with bars", len(B), flush=True)
    print("DONE", flush=True)

if __name__ == "__main__": main()
