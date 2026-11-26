"""Compare the frozen rule on real NQ futures 5-minute bars (Yahoo, about 60 days) with the QQQ version. Nothing is tuned."""
import json
import urllib.request as u
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.swing.intraday import Sess, load, sharpe
from app.research.swing.x22_audit import rewrite

F = Path("data/bars/lab/intraday/NQ_yahoo_5m.json")
if not F.exists():
    F.write_bytes(u.urlopen(u.Request("https://query1.finance.yahoo.com/v8/finance/chart/NQ=F?range=60d&interval=5m", headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
j = json.loads(F.read_text())["chart"]["result"][0]; q = j["indicators"]["quote"][0]
x = pd.DataFrame({k: q[n] for k, n in zip("ohlc", ("open", "high", "low", "close"))}, index=pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("America/New_York")).dropna()
x["d"] = x.index.tz_localize(None).normalize(); x["k"] = (x.index.hour * 60 + x.index.minute - 570) // 5
x = x[(x.k >= 0) & (x.k < 78)]; n = x.groupby("d").k.count(); x = x[x.d.isin(n[n >= 74].index)]
days = pd.DatetimeIndex(sorted(x.d.unique())); p = pd.Series(np.arange(len(days)), index=days); A = {c: np.full((len(days), 78), np.nan) for c in "ohlc"}
for c in "ohlc":
    A[c][x.d.map(p).to_numpy(), x.k.to_numpy()] = x[c].to_numpy()
c = pd.DataFrame(A["c"]).ffill(axis=1).bfill(axis=1).to_numpy(); o, h, l = (np.where(np.isnan(A[k]), c, A[k]) for k in "ohl")
cl = pd.Series(c[:, -1], index=days)
Q = load("QQQ"); qv = pd.Series(Q.vol, index=Q.days).reindex(days).ffill()  # same sizing input, because 60 days is too short to seed volatility
S = Sess("NQ", days, o, h, l, c, np.ones_like(c), qv.fillna(qv.dropna().iloc[0] if qv.notna().any() else .012).to_numpy(), cl.shift(1).to_numpy())
ny = pd.Series(rewrite(S, 14, len(days), bps=.25)[14:], index=days[14:])
a, z = int(Q.days.searchsorted(days[14])), len(Q.days); qq = pd.Series(rewrite(Q, a, z)[a:z], index=Q.days[a:z])
m = pd.concat({"NQ": ny, "QQQ": qq}, axis=1, join="inner")
print(f"real NQ bars: {days[0].date()}..{days[-1].date()}, {len(days)} full sessions, {len(ny)} tradable")
print(f"NQ futures rule: total {ny.sum()*100:.2f}% over {len(ny)} sessions, days traded {(ny!=0).mean():.0%}, Sharpe {sharpe(ny):.2f} (too few days to judge)")
print(f"matching {len(m)} days through Oct 30: NQ {m.NQ.sum()*100:.2f}%, QQQ {m.QQQ.sum()*100:.2f}%, daily correlation {m.corr().iloc[0,1]:.3f}, same sign on traded days {(np.sign(m.NQ)==np.sign(m.QQQ))[(m.NQ!=0)|(m.QQQ!=0)].mean():.0%}")
