"""Stress checks for the frozen Nasdaq rule. Reported only: no setting is chosen from this output."""
import numpy as np
import pandas as pd

from app.backtest.bumi import run as bumi_run
from app.research.swing.intraday import load, noise, sharpe, span
from app.research.swing.x24_real import mnq, nsx

q = load("QQQ"); a, _ = span(q, "val"); _, z = span(q, "final"); idx = q.days[a:z]
base = pd.Series(noise(q, a, z, look=14, every=6, vm=1.0)[0][a:z], index=idx)

print("1. Neighboring settings, out-of-sample 2020-Oct 2026, QQQ")
G = []
for lk in (7, 10, 14, 20, 30):
    for ev in (3, 6, 12):
        for vm in (.75, 1., 1.25, 1.5):
            G.append((lk, ev * 5, vm, sharpe(noise(q, a, z, look=lk, every=ev, vm=vm)[0][a:z])))
g = pd.DataFrame(G, columns=["look", "check_min", "band", "sharpe"])
print(f"  {len(g)} variants: Sharpe>0 {np.mean(g.sharpe>0):.0%}, >=.5 {np.mean(g.sharpe>=.5):.0%}, >=1 {np.mean(g.sharpe>=1):.0%}, median {g.sharpe.median():.2f}, min {g.sharpe.min():.2f}, frozen rule {sharpe(base):.2f}")
print("  median Sharpe by check interval:", g.groupby("check_min").sharpe.median().round(2).to_dict(), " by band:", g.groupby("band").sharpe.median().round(2).to_dict())

print("\n2. Placebo: same trade days and sizes with random direction (5,000 runs)")
rng = np.random.default_rng(5); x = base.to_numpy(); act = x != 0; gross = np.abs(x)
sims = np.array([sharpe(np.where(act, rng.choice([-1, 1], len(x)) * gross, 0)) for _ in range(5000)])
print(f"  frozen Sharpe {sharpe(x):.2f}; random-direction 95th percentile {np.percentile(sims,95):.2f}, share at or above frozen {np.mean(sims>=sharpe(x)):.3%}")

print("\n3. Rolling results, QQQ version")
m = base.rolling(252).sum().dropna(); print(f"  12-month return: worst {m.min()*100:.1f}%, median {m.median()*100:.1f}%, share of windows losing money {np.mean(m<0):.0%}")
e = base.cumsum(); under = (e < e.cummax()); run = (under != under.shift()).cumsum()[under]; print(f"  longest time below a prior high: {run.value_counts().max() if len(run) else 0} trading days")

n = nsx(); mq, _, _ = mnq(n, 100000); mq = mq / 100000
print("\n4. Fit with Bumi (Bumi modeled backtest), Jan 2020 onward")
bm, br = bumi_run(True); b = pd.Series(br.equity, index=pd.to_datetime(bm.dates)).pct_change().dropna()
j = pd.concat({"Bumi": b, "Rule QQQ": base, "Rule MNQ $100k": mq}, axis=1, join="inner").dropna()
print(f"  overlap {j.index[0].date()}..{j.index[-1].date()}, {len(j)} days; correlation to Bumi: QQQ version {j.Bumi.corr(j['Rule QQQ']):.2f}, MNQ version {j.Bumi.corr(j['Rule MNQ $100k']):.2f}")
for k, y in (("Bumi alone", j.Bumi), ("90% Bumi + 10% of account in rule risk", .9 * j.Bumi + .1 * j["Rule MNQ $100k"]), ("Bumi + rule on top, MNQ", j.Bumi + j["Rule MNQ $100k"]), ("Bumi + 0.5x rule on top, MNQ", j.Bumi + .5 * j["Rule MNQ $100k"])):
    c = (1 + y).cumprod(); print(f"  {k:<42}{(c.iloc[-1]**(252/len(y))-1)*100:6.1f}%/yr  Sharpe {sharpe(y):5.2f}  max DD {(c/c.cummax()-1).min()*100:6.1f}%")
