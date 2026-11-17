"""Market calendar, the stock list (universe) and the ORB bot's pre-market focus list."""

from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

from app import paths

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
SCAN_PY = paths.SKILL_DIR / "trader-scanner" / "scan.py"
SCANNER_DIR = paths.DATA_DIR / "scanner"          # universe.txt lives here
UNIVERSE_FILE = SCANNER_DIR / "trader" / "universe.txt"
UNIVERSE_MAX_AGE_DAYS = 7


@lru_cache(maxsize=1)
def scan_module() -> ModuleType:
    """day-trader-skill's scan.py, loaded as a module so its functions can be reused (never edited)."""
    spec = importlib.util.spec_from_file_location("dts_scan", SCAN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------- calendar

class Session:
    def __init__(self, day: date, open_: dtime, close: dtime):
        self.day, self.open, self.close = day, open_, close

    def at(self, t: dtime) -> datetime:
        return datetime.combine(self.day, t, tzinfo=NY)

    @property
    def early_close(self) -> bool:
        return self.close < dtime(16, 0)

    def __repr__(self) -> str:
        return f"Session({self.day} {self.open:%H:%M}-{self.close:%H:%M})"


class SkillCalendar:
    """The NYSE calendar built into day-trader-skill (2026-2027 holidays and early closes). Works offline."""

    def session(self, day: date) -> Session | None:
        s = scan_module().session(day)
        return Session(day, s[0], s[1]) if s else None


class AlpacaCalendar:
    """Alpaca's market calendar (live). Falls back to the skill's calendar if Alpaca can't be reached."""

    def __init__(self, trading_client):
        self.client = trading_client
        self.fallback = SkillCalendar()

    def session(self, day: date) -> Session | None:
        from alpaca.trading.requests import GetCalendarRequest
        try:
            days = self.client.get_calendar(GetCalendarRequest(start=day, end=day))
        except Exception as e:  # noqa: BLE001
            log.warning("Alpaca calendar failed (%s); using the built-in NYSE calendar", e)
            return self.fallback.session(day)
        for d in days:
            if d.date == day:
                return Session(day, d.open.time() if isinstance(d.open, datetime) else d.open,
                               d.close.time() if isinstance(d.close, datetime) else d.close)
        return None


# --------------------------------------------------------------------- universe

def ensure_universe(max_age_days: int = UNIVERSE_MAX_AGE_DAYS) -> list[str]:
    """US common stocks and ADRs from Nasdaq Trader (~5,900), refreshed weekly."""
    fresh = UNIVERSE_FILE.exists() and (
        time.time() - UNIVERSE_FILE.stat().st_mtime < max_age_days * 86400)
    if not fresh:
        SCANNER_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Refreshing the stock list from Nasdaq Trader")
        p = subprocess.run([sys.executable, str(SCAN_PY), "universe"], cwd=SCANNER_DIR,
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0 and not UNIVERSE_FILE.exists():
            raise RuntimeError(f"could not build the stock list: {(p.stderr or p.stdout).strip()}")
    return scan_module().symbols_from_file(str(UNIVERSE_FILE))


# ------------------------------------------------------------------- focus list

def pick_focus(data: dict, symbols: list[str], daily_hits: list[dict], fl: dict) -> dict:
    """Pure. data = {SYM: spark series} from the daily download.
    Focus = the N most traded (price x last session's volume) over the price floor,
    plus the most traded daily-scan hits (capped)."""
    liquid = []
    for sym in symbols:
        meta = (data.get(sym) or {}).get("meta") or {}
        price, vol = meta.get("regularMarketPrice"), meta.get("regularMarketVolume")
        if price is None or vol is None or price < fl["min_price"]:
            continue
        liquid.append((price * vol, sym))
    liquid.sort(key=lambda x: (-x[0], x[1]))
    top = [s for _, s in liquid[: fl["top_n_by_dollar_volume"]]]
    extra = []
    if fl.get("include_daily_scan_hits", True):
        for h in daily_hits:   # already most traded first
            if h["symbol"] not in top and h["symbol"] not in extra:
                extra.append(h["symbol"])
            if len(extra) >= fl.get("max_daily_scan_hits", 50):
                break
    return {"top": top, "daily_hits": extra, "symbols": top + extra}


def build_focus_list(fl: dict, out: Path, pause: float = 0.3) -> dict:
    """Pre-market: one download of daily closes for the whole universe, used both to rank by
    dollars traded and to run the repo's daily setups. Writes `out` (JSON) and returns it."""
    scan = scan_module()
    t0 = time.time()
    universe = ensure_universe()
    data, failed = scan.fetch_spark(universe, "3mo", "1d", pause)
    now_utc = scan.parse_now(None)
    hits, counts, last_date = scan.scan_daily(data, universe, now_utc, fl["min_price"],
                                              fl.get("min_daily_volume", 1_000_000))
    focus = pick_focus(data, universe, hits, fl)
    doc = {
        "created_at": datetime.now(NY).isoformat(timespec="seconds"),
        "closes_through": last_date.isoformat() if last_date else None,
        "universe": len(universe), "fetched": len(data), "failed": len(failed),
        "daily_scan": {"counts": counts, "hits": hits},
        "seconds": round(time.time() - t0, 1),
        **focus,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    return doc


def offline_symbols(path: Path) -> list[str]:
    """Every ticker in a saved bundle or folder (for replays)."""
    data, failed = scan_module().load_offline(str(path))
    return sorted(set(data) | set(failed))


def split_bundle(bundle: Path, folder: Path) -> Path:
    """A saved {TICKER: chart} bundle -> a folder of <TICKER>.json files (what entry.py reads)."""
    import gzip
    folder.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if str(bundle).endswith(".gz") else open
    with opener(bundle, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    for sym, chart in doc.items():
        (folder / f"{sym}.json").write_text(json.dumps(chart))
    return folder


def check_times(session: Session, settings: dict) -> list[datetime]:
    """When to check during the day: each bar close inside the scan window, plus the delay."""
    sch, win = settings["schedule"], settings["scan_window"]
    start = session.at(dtime.fromisoformat(win["start"]))
    end = min(session.at(dtime.fromisoformat(win["end"])), session.at(session.close))
    step = timedelta(minutes=sch["check_every_minutes"])
    delay = timedelta(minutes=sch["check_delay_minutes"])
    out, t = [], start
    while t <= end:
        out.append(t + delay)
        t += step
    return out
