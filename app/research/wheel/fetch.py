"""Survivorship-aware stock history from Alpaca: every US stock, active or delisted. Monthly bars pick the liquid
names; daily bars are cached only for names that were ever liquid. Run: python -m app.research.wheel.fetch"""
from __future__ import annotations
import gzip, json, re, sys, time, urllib.parse, urllib.request
from app import settings
from app.research.data import LAB
DIR = LAB / "wheel"; DAILY = DIR / "d"
NOT_STOCK = re.compile(r"\b(ETF|ETN|FUND|TRUST|PORTFOLIO|INDEX|ULTRA|PROSHARES|DIREXION|ISHARES|SPDR|VANGUARD|INVESCO QQQ|2X|3X|WARRANT|RIGHTS?|UNITS?|PREFERRED|NOTES?|DEPOSITARY SHARES)\b", re.I)
_last = [0.0]

def _hdr():
    settings.load_env(); a = settings.alpaca_settings()
    return {"APCA-API-KEY-ID": a.api_key, "APCA-API-SECRET-KEY": a.secret_key, "Accept": "application/json"}

def _get(url, hdr):
    for k in range(8):
        wait = .32 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if k == 7: raise
            time.sleep(2 + 3 * k)

def assets(hdr):
    f = DIR / "assets.json"
    if f.exists(): return json.loads(f.read_text())
    out = []
    for st in ("active", "inactive"):
        for x in _get(f"https://paper-api.alpaca.markets/v2/assets?status={st}&asset_class=us_equity", hdr):
            if x.get("exchange") in ("OTC", "CRYPTO") and st == "active": continue
            if not re.fullmatch(r"[A-Z]{1,5}", x["symbol"]) or NOT_STOCK.search(x.get("name") or ""): continue
            out.append({"s": x["symbol"], "name": x.get("name"), "status": st, "ex": x.get("exchange"), "opt": "has_options" in (x.get("attributes") or [])})
    seen = {}
    for x in out: seen.setdefault(x["s"], x)
    out = list(seen.values()); DIR.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(out)); return out

def bars(syms, tf, adj, hdr, start="2015-01-01", end="2026-11-20"):
    out = {s: [] for s in syms}; tok = None
    while True:
        q = {"symbols": ",".join(syms), "timeframe": tf, "start": start, "end": end, "adjustment": adj, "feed": "sip", "limit": 10000, "sort": "asc"}
        if tok: q["page_token"] = tok
        d = _get("https://data.alpaca.markets/v2/stocks/bars?" + urllib.parse.urlencode(q), hdr)
        for s, v in (d.get("bars") or {}).items():
            out[s] += [[x["t"][:10], x["o"], x["h"], x["l"], x["c"], x["v"]] for x in v]
        tok = d.get("next_page_token")
        if not tok: return out

def main():
    hdr = _hdr(); A = assets(hdr); S = [x["s"] for x in A]; print("assets", len(A), "active", sum(x["status"] == "active" for x in A), flush=True)
    f = DIR / "monthly.json.gz"
    if f.exists(): M = json.load(gzip.open(f, "rt"))
    else:
        M = {}
        for i in range(0, len(S), 150):
            for s, v in bars(S[i:i + 150], "1Month", "raw", hdr).items():
                if v: M[s] = [[x[0][:7], x[4], x[4] * x[5]] for x in v]
            if i % 1500 == 0: print("monthly", i, flush=True)
        json.dump(M, gzip.open(f, "wt"))
    by = {}
    for s, v in M.items():
        for mo, c, dv in v:
            if c >= 5: by.setdefault(mo, []).append((dv, s))
    top = {mo: [s for _, s in sorted(x, reverse=True)[:500]] for mo, x in by.items()}
    (DIR / "top500.json").write_text(json.dumps(top)); need = sorted({s for x in top.values() for s in x}); print("ever top-500", len(need), flush=True)
    DAILY.mkdir(parents=True, exist_ok=True); todo = [s for s in need if not (DAILY / f"{s}.json.gz").exists()]
    for i in range(0, len(todo), 40):
        for s, v in bars(todo[i:i + 40], "1Day", "all", hdr).items():
            with gzip.open(DAILY / f"{s}.json.gz", "wt") as h: json.dump(v, h)
        if i % 400 == 0: print("daily", i, "of", len(todo), flush=True)
    print("DONE", len(need), flush=True)

if __name__ == "__main__": main()
