"""Step 8: the single holdout run of the system in FROZEN.md."""
import numpy as np
import pandas as pd

from app.research.swing.lab import load, stats
from app.research.swing.sized import MULT, run

A, Z = "2019-01-01", "2024-03-28"
d = load(); cols = list(MULT); sp = d.ret["SP500"].fillna(0).loc[A:Z]
r1 = run(d, 50000, cols, start="2017-01-01", end=Z)[0].loc[A:Z]
r2 = run(d, 50000, cols, start="2017-01-01", end=Z, cost_mult=2)[0].loc[A:Z]
S = {"Trend sleeve": r1, "S&P futures": sp, "S&P + 0.5 trend": sp + .5 * r1, "Trend, 2x costs": r2, "S&P + 0.5 trend, 2x": sp + .5 * r2}
T = {k: stats(v) for k, v in S.items()}
print(f"{'':<24}{'ret%':>7}{'vol%':>7}{'Sharpe':>8}{'DD%':>8}")
for k, s in T.items():
    print(f"{k:<24}{s['ret']*100:7.1f}{s['vol']*100:7.1f}{s['sharpe']:8.2f}{s['dd']*100:8.1f}")
a, b, c, e = T["Trend sleeve"], T["S&P futures"], T["S&P + 0.5 trend"], T["S&P + 0.5 trend, 2x"]
C = [("1 sleeve Sharpe >= .30", a["sharpe"] >= .3), ("2 beats S&P on return and Sharpe", c["ret"] > b["ret"] and c["sharpe"] > b["sharpe"]),
     ("3 drawdown no worse", c["dd"] >= b["dd"]), ("4 holds at 2x costs", T["Trend, 2x costs"]["sharpe"] >= .3 and e["ret"] > b["ret"] and e["sharpe"] > b["sharpe"])]
for k, v in C:
    print(("PASS " if v else "FAIL ") + k)
print("VERDICT:", "PASS" if all(v for _, v in C) else "FAIL")
print("\nBy year, %")
print(pd.DataFrame({k: v.groupby(v.index.year).apply(lambda x: ((1 + x).prod() - 1) * 100) for k, v in list(S.items())[:3]}).round(1).to_string())
rng = np.random.default_rng(7); x = pd.DataFrame({"a": sp, "b": sp + .5 * r1}).to_numpy(); n = len(x); dif = []
for _ in range(3000):
    i = np.concatenate([np.arange(j, j + 20) % n for j in rng.integers(0, n, n // 20 + 1)])[:n]; y = x[i]
    dif.append(y[:, 1].mean() / y[:, 1].std() * 16 - y[:, 0].mean() / y[:, 0].std() * 16)
print(f"\nSharpe gain vs S&P {np.mean(dif):.2f}, chance gain is above zero {np.mean(np.array(dif) > 0):.0%}")
print("Sleeve excluding 2022:", {k: round(v, 2) for k, v in stats(r1[r1.index.year != 2022]).items() if k in ("ret", "sharpe", "dd")})
print("Overlay excluding 2022:", round(stats((sp + .5 * r1)[sp.index.year != 2022])["sharpe"], 2), "vs S&P", round(stats(sp[sp.index.year != 2022])["sharpe"], 2))
