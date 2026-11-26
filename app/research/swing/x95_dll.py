"""Exploratory (2026-11-25, all data already seen): Swing v1.1 with a daily loss limit, and what happens after a losing trade.
DLL: at each 5-minute close, if the day's realized + open P&L <= -X of the $100k base, go flat at the next open and stop for the day."""
import numpy as np, pandas as pd
from app.research.swing.intraday import load
from app.strategies.swing import BARS, CANDLE, LOOKBACK, Machine, update_fvg
s = load("QQQ")


def run(limit=None, trades_out=None):
    candles, lo, hi = [], None, None; daily = {}
    for i in range(len(s.days)):
        if i >= LOOKBACK and np.isfinite(s.vol[i]) and s.vol[i] > 0 and np.isfinite(s.prev[i]):
            sigma = np.nanmean(np.abs(s.c[i - LOOKBACK:i] / s.o[i - LOOKBACK:i, 0, None] - 1), axis=0)
            m = Machine.start({"prev": float(s.prev[i]), "weight": min(2.0, .01 / s.vol[i]), "sigma": list(sigma), "candles": candles, "lo": lo, "hi": hi}, s.o[i, 0], True)
            stopped = False; seq = []; last = 0.0; held = 0
            for b in range(BARS):
                m.step(b, s.o[i], s.h[i], s.l[i], s.c[i])
                if stopped:
                    m.side = 0
                if trades_out is not None and m.held != held:        # a trade closed at this bar's open
                    if held:
                        seq.append(m.pnl - last)
                    last = m.pnl if not m.held else m.pnl + m.cost * m.weight
                    held = m.held
                mark = m.pnl + (m.held * (s.c[i, b] / m.entry - 1) * m.weight if m.held else 0.0)
                if limit is not None and not stopped and mark <= -limit:
                    stopped, m.side = True, 0
            if trades_out is not None:
                if held:
                    seq.append(m.pnl - last)
                trades_out.append((s.days[i], seq, m.pnl))
            daily[s.days[i]] = m.pnl
        for k in range(CANDLE - 1, BARS, CANDLE):
            candles, lo, hi = update_fvg(candles, lo, hi, s.h[i, k - 2:k + 1].max(), s.l[i, k - 2:k + 1].min(), s.c[i, k])
    return pd.Series(daily).loc["2016-01-01":"2026-10-31"]


def line(name, r):
    yrs = len(r) / 252; e = (1 + r).cumprod()
    w = {k: r.loc[a:z].mean() / r.loc[a:z].std() * np.sqrt(252) for k, (a, z) in {"16-19": ("2016", "2019"), "20-22": ("2020", "2022"), "23-26": ("2023", "2026")}.items()}
    print(f"{name:10} {((1 + r).prod() ** (1 / yrs) - 1) * 100:5.1f}%/yr  Sharpe {r.mean() / r.std() * np.sqrt(252):.2f}  max drop {(e / e.cummax() - 1).min() * 100:5.1f}%  "
          f"worst day {r.min() * 100:5.2f}%  " + "  ".join(f"{k} {v:.2f}" for k, v in w.items()))


T = []
line("no limit", run(None, T))
for x in (.03, .015, .01, .0075, .005):
    line(f"limit {x * 100:.2f}%", run(x))
d = [(day, seq, tot) for day, seq, tot in T if day >= pd.Timestamp("2016-01-01") and len(seq) >= 2 and seq[0] < 0]
after = [sum(seq[1:]) for _, seq, _ in d]
print(f"\nDays whose first trade lost and Swing traded again: {len(d)}")
print(f"  re-entries made money overall: {np.mean([a > 0 for a in after]):.0%} of those days · avg re-entry P&L {np.mean(after) * 1e5:+,.0f} $ (at $100k)")
print(f"  day ended positive anyway: {np.mean([tot > 0 for _, _, tot in d]):.0%} · avg day {np.mean([tot for _, _, tot in d]) * 1e5:+,.0f} $")
nxt = [seq[1] for _, seq, _ in d]
print(f"  the very next trade after a loss: win rate {np.mean([x > 0 for x in nxt]):.0%}, avg {np.mean(nxt) * 1e5:+,.0f} $")
allfirst = [seq[0] for day, seq, _ in T if day >= pd.Timestamp("2016-01-01") and seq]
print(f"  (for comparison, every first trade of a day: win rate {np.mean([x > 0 for x in allfirst]):.0%}, avg {np.mean(allfirst) * 1e5:+,.0f} $)")
