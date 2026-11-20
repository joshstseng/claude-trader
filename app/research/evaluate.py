"""Scoring for the research lab, with the pass bar fixed before any testing (2026-11-20, agreed with the user):

    built and tuned on 2021–2023 ("train"); then ONE look at 2024–2026 ("test"); 2016–2020 ("before") is extra
    history that was never used for tuning either. After costs, on a $50k account risking 1% a trade:
      - profit factor >= 1.3 in train AND in test
      - 100+ trades over 2021–2026
      - most years positive (2021–2026)
      - worst drawdown under 20% of the account ($10,000)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

ACCOUNT = 50_000.0
RISK = 0.01


@dataclass
class Trade:
    sym: str
    side: int                 # +1 long, -1 short
    t_in: datetime
    t_out: datetime
    p_in: float
    p_out: float
    qty: float
    cost: float = 0.0         # $ (commission + slippage)
    note: str = ""

    @property
    def pnl(self) -> float:
        return (self.p_out - self.p_in) * self.side * self.qty - self.cost


@dataclass
class Stats:
    n: int = 0
    wins: int = 0
    pnl: float = 0.0
    gross_win: float = 0.0
    gross_loss: float = 0.0
    max_dd: float = 0.0
    years: dict = field(default_factory=dict)

    @property
    def pf(self) -> float:
        return self.gross_win / self.gross_loss if self.gross_loss else float("inf")

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0


def stats(trades: list[Trade], y0: int, y1: int) -> Stats:
    s = Stats()
    run = peak = 0.0
    yr = defaultdict(float)
    for t in sorted(trades, key=lambda x: x.t_out):
        if not (y0 <= t.t_out.year <= y1):
            continue
        p = t.pnl
        s.n += 1
        s.pnl += p
        s.wins += p > 0
        if p > 0:
            s.gross_win += p
        else:
            s.gross_loss -= p
        run += p
        peak = max(peak, run)
        s.max_dd = min(s.max_dd, run - peak)
        yr[t.t_out.year] += p
    s.years = dict(sorted(yr.items()))
    return s


def verdict(trades: list[Trade]) -> tuple[bool, dict]:
    tr, te, al, pre = stats(trades, 2021, 2023), stats(trades, 2024, 2026), stats(trades, 2021, 2026), stats(trades, 2016, 2020)
    pos = sum(v > 0 for v in al.years.values())
    checks = {
        "PF train >= 1.3": tr.pf >= 1.3,
        "PF test >= 1.3": te.pf >= 1.3,
        "100+ trades": al.n >= 100,
        "most years positive": pos > len(al.years) / 2,
        "drawdown < $10k": al.max_dd > -0.2 * ACCOUNT,
    }
    return all(checks.values()), {"train": tr, "test": te, "all": al, "before": pre, "checks": checks}


def line(name: str, trades: list[Trade], show_test: bool = False) -> str:
    """One summary line. The test half is hidden unless show_test (one look per finalist)."""
    ok, v = verdict(trades)
    tr, al, pre = v["train"], v["all"], v["before"]
    s = (f"{name[:44]:44} train n={tr.n:4} pf={tr.pf:4.2f} ${tr.pnl:>+8,.0f} dd=${tr.max_dd:>+7,.0f} "
         f"| before pf={pre.pf:4.2f} ${pre.pnl:>+8,.0f}")
    if show_test:
        te = v["test"]
        s += (f" | TEST n={te.n} pf={te.pf:.2f} ${te.pnl:+,.0f} | 21-26 n={al.n} dd=${al.max_dd:+,.0f} "
              f"yrs {' '.join(f'{y % 100}:{p / 1000:+.1f}k' for y, p in al.years.items())} | {'PASS' if ok else 'fail'}")
    return s
