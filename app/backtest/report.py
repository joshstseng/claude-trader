"""Backtest metrics and the readable report for one run."""

from __future__ import annotations

import statistics as st
from collections import Counter, defaultdict
from itertools import groupby

from app.backtest.signals import BtSignal

BLIND_SPOTS = [
    "**Delisted stocks are missing**: the stock list is today's, so companies delisted since are left out "
    "(results look slightly better than reality).",
    "**Costs are assumed** (0.03% of the price per side) until Step 1b measures real paper fills.",
    "**5-minute bars only**: inside one bar we can't see whether the stop or the target came first, so "
    "both in one bar counts as a stop. Entries are at the trigger bar's close (live is ~1 minute later).",
    "**Data**: Alpaca's full-market (SIP) bars. Live alerts use Yahoo; prices match, and the volume "
    "filter agrees ~94% of the time.",
]


def _r(x: float) -> str:
    return f"{x:+.3f}R".replace("-", "−")


def _usd(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.0f}"


def _usd2(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def metrics(trades: list[BtSignal]) -> dict:
    """Trades in time order -> the numbers that matter."""
    t = [s for s in trades if (s.outcome or {}).get("r_net") is not None]
    if not t:
        return {"trades": 0}
    r = [s.outcome["r_net"] for s in t]
    usd = [s.outcome["pnl_usd"] or 0.0 for s in t]
    res = Counter(s.outcome["result"] for s in t)
    wins_usd, losses_usd = sum(u for u in usd if u > 0), -sum(u for u in usd if u < 0)

    daily_usd, daily_r = defaultdict(float), defaultdict(float)
    for s, rr, u in zip(t, r, usd):
        daily_usd[s.day] += u
        daily_r[s.day] += rr

    def drawdown(daily: dict) -> float:
        eq = peak = dd = 0.0
        for d in sorted(daily):
            eq += daily[d]
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        return dd

    streak = worst_streak = 0
    for rr in r:
        streak = streak + 1 if rr < 0 else 0
        worst_streak = max(worst_streak, streak)
    winners, losers = [x for x in r if x > 0], [x for x in r if x <= 0]
    return {
        "trades": len(t), "days": len(daily_usd),
        "target": res["target"], "stop": res["stop"], "flat": res["flat"],
        "win_rate": len(winners) / len(t),
        "avg_r": st.mean(r), "avg_r_gross": st.mean(s.outcome["r_gross"] for s in t),
        "avg_win_r": st.mean(winners) if winners else 0.0, "avg_loss_r": st.mean(losers) if losers else 0.0,
        "total_r": sum(r), "total_usd": sum(usd), "avg_usd": st.mean(usd),
        "profit_factor": (wins_usd / losses_usd) if losses_usd else None,
        "max_dd_usd": drawdown(daily_usd), "max_dd_r": drawdown(daily_r),
        "worst_losing_streak": worst_streak,
        "green_days": sum(1 for v in daily_usd.values() if v > 0) / len(daily_usd),
        "best_day_usd": max(daily_usd.values()), "worst_day_usd": min(daily_usd.values()),
        "reached_1r": sum(1 for s in t if (s.outcome.get("mfe_r") or 0) >= 1) / len(t),
        "reached_2r": sum(1 for s in t if (s.outcome.get("mfe_r") or 0) >= 2) / len(t),
    }


def breakdown(trades: list[BtSignal], key) -> list[tuple[str, int, float, float]]:
    """[(group, trades, avg R, total $)] grouped by key(signal)."""
    groups = defaultdict(list)
    for s in trades:
        if (s.outcome or {}).get("r_net") is not None:
            groups[key(s)].append(s)
    return [(k, len(v), st.mean(x.outcome["r_net"] for x in v), sum(x.outcome["pnl_usd"] or 0 for x in v))
            for k, v in sorted(groups.items())]


def stop_bucket(s: BtSignal) -> str:
    p = (s.risk_per_share or 0) / (s.entry or 1) * 100
    return "a. under 0.25%" if p < .25 else "b. 0.25–0.5%" if p < .5 else "c. 0.5–1%" if p < 1 else "d. 1–2%" if p < 2 else "e. 2%+"


def _line(m: dict) -> str:
    if not m.get("trades"):
        return "| no trades | | | | | |"
    pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else "–"
    return (f"| {m['trades']:,} | {m['win_rate'] * 100:.0f}% | **{_r(m['avg_r'])}** | {_usd(m['total_usd'])} | "
            f"{pf} | {_usd(m['max_dd_usd'])} |")


def render(*, run_id: int, label: str, settings_line: str, code: str, views: dict[str, dict], tag: str = "ORB",
           traded: list[BtSignal], every: list[BtSignal], why_not: Counter,
           baseline: tuple[int, str, dict] | None) -> str:
    """The markdown report. views: {name: metrics}; the first is the headline (as traded)."""
    head_name, m = next(iter(views.items()))
    out = [f"# {tag} backtest run #{run_id}: {label}", "", settings_line, f"Code: `{code}`", ""]
    if m.get("trades"):
        verdict = "has an edge" if m["avg_r"] > 0 else "loses money"
        out += [f"## Headline: {head_name[0].lower() + head_name[1:]}", "",
                f"**{m['trades']:,} trades over {m['days']} days · {_r(m['avg_r'])} a trade after costs "
                f"({_usd2(m['avg_usd'])}) · total {_usd(m['total_usd'])}: as set up, this {verdict}.**", "",
                "| | |", "|---|---|",
                f"| Target ✅ / stop ❌ / flat ➖ | {m['target']:,} / {m['stop']:,} / {m['flat']:,} |",
                f"| Win rate (made money) | {m['win_rate'] * 100:.0f}% |",
                f"| Average winner / loser | {_r(m['avg_win_r'])} / {_r(m['avg_loss_r'])} |",
                f"| Before costs | {_r(m['avg_r_gross'])} a trade |",
                f"| Profit factor ($ won ÷ $ lost) | {m['profit_factor']:.2f} |" if m["profit_factor"] else "| Profit factor | – |",
                f"| Worst drawdown | {_usd(m['max_dd_usd'])} ({m['max_dd_r']:+.1f}R) |",
                f"| Worst losing streak | {m['worst_losing_streak']} trades |",
                f"| Green days | {m['green_days'] * 100:.0f}% (best {_usd(m['best_day_usd'])}, worst {_usd(m['worst_day_usd'])}) |",
                f"| Reached +1R / +2R before exiting | {m['reached_1r'] * 100:.0f}% / {m['reached_2r'] * 100:.0f}% |", ""]
    out += ["## Views", "", "| View | Trades | Win rate | Avg per trade | Total | Profit factor | Worst drawdown |",
            "|---|---|---|---|---|---|---|"]
    out += [f"| {name} " + _line(v) for name, v in views.items()]
    out.append("")
    if baseline:
        bid, blabel, bm = baseline
        if bm.get("trades") and m.get("trades"):
            out += [f"## Compared with baseline run #{bid} ({blabel})", "",
                    "| | Baseline | This run | Change |", "|---|---|---|---|",
                    f"| Trades | {bm['trades']:,} | {m['trades']:,} | {m['trades'] - bm['trades']:+,} |",
                    f"| Avg per trade | {_r(bm['avg_r'])} | {_r(m['avg_r'])} | **{m['avg_r'] - bm['avg_r']:+.3f}R** |",
                    f"| Total | {_usd(bm['total_usd'])} | {_usd(m['total_usd'])} | {_usd(m['total_usd'] - bm['total_usd'])} |",
                    f"| Win rate | {bm['win_rate'] * 100:.0f}% | {m['win_rate'] * 100:.0f}% | {(m['win_rate'] - bm['win_rate']) * 100:+.0f} pts |",
                    f"| Worst drawdown | {_usd(bm['max_dd_usd'])} | {_usd(m['max_dd_usd'])} | {_usd(m['max_dd_usd'] - bm['max_dd_usd'])} |", ""]
    out += ["## By month (as traded)", "", "| Month | Trades | Avg per trade | Total |", "|---|---|---|---|"]
    out += [f"| {k} | {n} | {_r(a)} | {_usd(u)} |" for k, n, a, u in breakdown(traded, lambda s: s.day[:7])]
    out += ["", "## By trigger time (every signal)", "", "| Bar closing | Signals | Avg per trade | Total |",
            "|---|---|---|---|"]
    out += [f"| {k} | {n:,} | {_r(a)} | {_usd(u)} |"
            for k, n, a, u in breakdown(every, lambda s: s.trigger_time[:4] + "0s")]
    out += ["", "## By stop distance (every signal)", "", "| Stop distance (% of price) | Signals | Avg per trade | Total |",
            "|---|---|---|---|"]
    out += [f"| {k[3:]} | {n:,} | {_r(a)} | {_usd(u)} |" for k, n, a, u in breakdown(every, stop_bucket)]
    out += ["", "## Why signals weren't traded", "", "| Reason | Signals |", "|---|---|"]
    out += [f"| {k} | {n:,} |" for k, n in why_not.most_common()]
    out += ["", "## Blind spots", ""] + [f"- {b}" for b in BLIND_SPOTS]
    return "\n".join(out) + "\n"
