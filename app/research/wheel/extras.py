"""Alpaca's asset list omits many delisted tickers, though their bars still exist. This adds the failures and collapses
that a survivorship-free test must contain. Tickers ending in Q are usually the bankruptcy ticker."""
from __future__ import annotations
import gzip, json
from app.research.wheel.fetch import DAILY, DIR, _hdr, bars
FAILED = """SIVB SIVBQ SBNY FRC FRCB BBBYQ JCPNQ SHLDQ HTZGQ CHKAQ DNRCQ WFTIQ CBLAQ SPWRQ RADCQ WEWKQ BIGGQ PRTYQ TUPBQ NKLAQ FSRNQ
RIDEQ LAZRQ SAVEQ YELLQ REVRQ APRNQ ENDPQ MNKKQ FTRCQ WINMQ GNCIQ PIRRQ ASNAQ TLRDQ DOFSQ OASPQ GPORQ AKRXQ EXPRQ BRDSQ CANOQ DBDQQ AVYAQ
UPLCQ SNDEQ CPEGQ HKRSQ ULTRQ AMPYQ CRCQQ VLCCF NEBLQ VALPQ PACDQ CHAPQ HALLQ LBRT_ BPTH_ MBIIQ GTXMQ NUVGQ CLVSQ ATIPQ BBIGQ AGRXQ""".split()
MAYBE = """CHK DNR WFT JCP SHLD RAD WE BIG PRTY TUP NKLA FSR RIDE LAZR SAVE YELL REV APRN ENDP MNK FTR WIN GNC PIR ASNA TLRD DO OAS GPOR AKRX EXPR BRDS CANO DBD AVYA
UPL SN CPE HK ULTR CRC NE VAL ESV PACD WLL SD EP HLX MULN FFIE BBIG VLDR XOS ARVL GOEV PSNY SPCE CLOV SKLZ BLUE BYND VRM OPEN WISH CGC TLRY ACB BKKT VRX BHC TEVA FOSL CHS EV PCG X BHGE
ANDV APC ATVI CELG CERN CTXS DISCA DISCB EVHC FB FLIR GWPH HFC INFO KSU LB MXIM NLSN PBCT RHT SIVB SBNY TIF TWTR VAR WBA WRK XLNX PACW CS""".split()

def main():
    hdr = _hdr(); M = json.load(gzip.open(DIR / "monthly.json.gz", "rt")); want = [s.replace("_", "") for s in dict.fromkeys(FAILED + MAYBE)]
    todo = [s for s in want if s not in M]
    for i in range(0, len(todo), 80):
        for s, v in bars(todo[i:i + 80], "1Month", "raw", hdr).items():
            if v: M[s] = [[x[0][:7], x[4], x[4] * x[5]] for x in v]
    json.dump(M, gzip.open(DIR / "monthly.json.gz", "wt"))
    got = [s for s in want if s in M]; print("extras with data", len(got), "of", len(want), flush=True)
    # a ticker reused by a new company: keep the bankruptcy version when both carry the same history
    drop = {b for b in got if b + "Q" in M and [x[0] for x in M[b]][:6] == [x[0] for x in M[b + "Q"]][:6]}
    by = {}
    for s, v in M.items():
        if s in drop: continue
        for mo, c, dv in v:
            if c >= 5: by.setdefault(mo, []).append((dv, s))
    top = {mo: [s for _, s in sorted(x, reverse=True)[:500]] for mo, x in by.items()}
    (DIR / "top500.json").write_text(json.dumps(top)); (DIR / "dropped.json").write_text(json.dumps(sorted(drop)))
    (DIR / "failed.json").write_text(json.dumps(sorted(s for s in got if s in FAILED or s in ("SIVB", "SBNY", "FRC"))))
    need = sorted({s for x in top.values() for s in x} | {s for s in got if s not in drop}); todo = [s for s in need if not (DAILY / f"{s}.json.gz").exists()]
    print("need", len(need), "new daily", len(todo), flush=True)
    for i in range(0, len(todo), 40):
        for s, v in bars(todo[i:i + 40], "1Day", "all", hdr).items():
            with gzip.open(DAILY / f"{s}.json.gz", "wt") as h: json.dump(v, h)
    for s in drop: (DAILY / f"{s}.json.gz").unlink(missing_ok=True)
    (DIR / "panel.pkl").unlink(missing_ok=True); print("DONE", flush=True)

if __name__ == "__main__": main()
