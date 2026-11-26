"""Read-only: does the free real-time IEX feed produce the same Swing v1.1 decisions as the consolidated SIP feed?
Replays recent sessions through the live rules. Places no orders."""
from datetime import datetime, time as dtime, timedelta

import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient

from app import settings, swing_live as L
from app.strategies.swing import BARS, Machine, context
from app.swing_run import bar_rows

settings.load_env(); a = settings.alpaca_settings(); data = StockHistoricalDataClient(a.api_key, a.secret_key)
end = datetime(2026, 11, 21, tzinfo=L.NY); start = end - timedelta(days=420)
ds, So, Sh, Sl, Sc = L.matrix(bar_rows(data, "QQQ", start, end, DataFeed.SIP))
ir = bar_rows(data, "QQQ", end - timedelta(days=130), end, DataFeed.IEX)
frame = pd.DataFrame(ir, columns=["t", "o", "h", "l", "c"]); t = pd.to_datetime(frame.t, utc=True).dt.tz_convert(L.NY); frame["d"] = t.dt.tz_localize(None).dt.normalize()
rows = {d: [(x.t, x.o, x.h, x.l, x.c) for x in g.itertuples()] for d, g in frame.groupby("d")}
out = []; same = total = 0
for i in range(len(ds) - 60, len(ds)):
    d = ds[i]
    if d not in rows:
        continue
    got = L.today_arrays(rows[d], BARS - 1)
    if got is None:
        continue
    Io, Ih, Il, Ic = got; ctx = context(So[:i], Sh[:i], Sl[:i], Sc[:i]); M, N = Machine.start(ctx, So[i, 0], True), Machine.start(ctx, Io[0], True)
    for b in range(BARS):
        M.step(b, So[i], Sh[i], Sl[i], Sc[i]); N.step(b, Io, Ih, Il, Ic)
        if b in range(5, 77):
            total += 1; same += M.side == N.side
    out.append((d, M.pnl * 1e5, N.pnl * 1e5, M.trades, N.trades))
x = pd.DataFrame(out, columns=["day", "sip", "iex", "sip_trades", "iex_trades"]).set_index("day")
print(f"sessions {len(x)} ({x.index[0].date()}..{x.index[-1].date()}); wanted position matched on {same/total:.1%} of bars")
print(f"model P&L at $100k: SIP ${x.sip.sum():,.0f}, IEX ${x.iex.sum():,.0f}; daily correlation {x.sip.corr(x.iex):.3f}; trades SIP {x.sip_trades.sum()}, IEX {x.iex_trades.sum()}; sessions with different trade counts {(x.sip_trades != x.iex_trades).sum()}")
print(f"largest one-day difference ${(x.sip - x.iex).abs().max():,.0f}")
