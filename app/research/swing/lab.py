"""Swing futures research lab: roll-adjusted daily data, forecasts and a cost-aware portfolio simulator.

Windows are frozen before any result was seen:
  dev   start .. 2012-12-31   (free to explore)
  val   2013-01-01 .. 2018-12-31   (checks candidates chosen on dev)
  hold  2019-01-01 .. 2024-03-28   (run once on the final frozen system)

Signals use the close of day t. The position is traded at the close of t+1 and earns from t+2, so
there is a full day of delay. Costs are one full bid-ask spread per side plus commission.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3] / "data/bars/lab/swing/carver"
WINDOWS = {"dev": ("1900-01-01", "2012-12-31"), "val": ("2013-01-01", "2018-12-31"), "hold": ("2019-01-01", "2024-03-28")}

GROUPS = {
    "equity": ["SP500", "NASDAQ", "DOW", "RUSSELL", "SP400"],
    "metals": ["GOLD", "SILVER", "COPPER", "PLAT", "PALLAD"],
    "energy": ["CRUDE_W", "HEATOIL", "GASOILINE", "GAS_US"],
    "rates": ["US2", "US5", "US10", "US20", "US30"],
    "fx": ["EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD", "MXP"],
    "ags": ["CORN", "SOYBEAN", "WHEAT", "REDWHEAT", "SOYOIL", "SOYMEAL", "LIVECOW", "FEEDCOW", "LEANHOG"],
}
COMMISSION = 7.0  # dollars per full-size-equivalent contract per side (micro commissions scaled up)


def _daily(path: Path, col: str | None = None) -> pd.Series | pd.DataFrame:
    x = pd.read_csv(path, parse_dates=["DATETIME"], index_col="DATETIME")
    x = x.groupby(x.index.normalize()).last()
    x = x[x.index.dayofweek < 5]
    return x[col] if col else x


@dataclass
class Data:
    adj: pd.DataFrame
    price: pd.DataFrame
    carry: pd.DataFrame
    ret: pd.DataFrame
    vol: pd.DataFrame
    cost: pd.Series
    group: dict


def load() -> Data:
    cfg = pd.read_csv(ROOT / "instrumentconfig.csv").set_index("Instrument")
    spread = pd.read_csv(ROOT / "spreadcosts.csv").set_index("Instrument")["SpreadCost"]
    names = [s for g in GROUPS.values() for s in g]
    adj, price, carry, cost = {}, {}, {}, {}
    for s in names:
        adj[s] = _daily(ROOT / "adj" / f"{s}.csv", "price")
        m = _daily(ROOT / "mult" / f"{s}.csv")
        price[s] = m["PRICE"].ffill()
        with np.errstate(all="ignore"):
            yrs = (_ym(m["CARRY_CONTRACT"]) - _ym(m["PRICE_CONTRACT"]))
            carry[s] = ((m["PRICE"] - m["CARRY"]) / yrs.where(yrs != 0)).ffill(limit=5)
        cost[s] = float(spread.get(s, np.nan)) + COMMISSION / float(cfg.loc[s, "Pointsize"])  # points per side
    A = pd.DataFrame(adj).sort_index()
    A = A[A.index <= "2024-03-28"]
    P = pd.DataFrame(price).reindex(A.index).ffill(limit=5)
    C = pd.DataFrame(carry).reindex(A.index).ffill(limit=5)
    D = A.ffill(limit=5).diff()
    R = (D / P.shift(1)).where(P.shift(1) > 0).clip(-.5, .5)
    V = D.ewm(span=32, min_periods=32).std().clip(lower=1e-9)  # daily volatility in price points
    group = {s: g for g, xs in GROUPS.items() for s in xs}
    return Data(A.ffill(limit=5), P, C, R, V, pd.Series(cost), group)


def _ym(x: pd.Series) -> pd.Series:
    x = x.astype(float)
    return (x // 10000) + ((x // 100) % 100 - 1) / 12


def ewmac(d: Data, fast: int) -> pd.DataFrame:
    scal = {4: 7.5, 8: 5.3, 16: 3.75, 32: 2.65, 64: 1.87}[fast]
    f = d.adj.ewm(span=fast, min_periods=fast).mean() - d.adj.ewm(span=4 * fast, min_periods=4 * fast).mean()
    return (f / d.vol * scal / 10).clip(-2, 2)


def breakout(d: Data, n: int) -> pd.DataFrame:
    hi, lo = d.adj.rolling(n, min_periods=n).max(), d.adj.rolling(n, min_periods=n).min()
    x = 40 * (d.adj - (hi + lo) / 2) / (hi - lo).replace(0, np.nan)
    return (x.ewm(span=max(2, n // 4)).mean() / 10 * 1.0).clip(-2, 2)


def tsmom(d: Data, n: int = 252) -> pd.DataFrame:
    return np.sign(d.adj - d.adj.shift(n)).where(d.adj.shift(n).notna())


def carry(d: Data, span: int = 90) -> pd.DataFrame:
    ann = d.vol * 16
    return (d.carry / ann * 30 / 10).ewm(span=span, min_periods=20).mean().clip(-2, 2)


def reversal(d: Data, n: int = 5) -> pd.DataFrame:
    z = (d.adj - d.adj.shift(n)) / (d.vol * np.sqrt(n))
    return (-z / 1.5).clip(-2, 2)


def weights(d: Data, cols) -> pd.Series:
    by = {}
    for s in cols:
        by.setdefault(d.group[s], []).append(s)
    return pd.Series({s: 1 / len(by) / len(xs) for xs in by.values() for s in xs})


def simulate(d: Data, fc: pd.DataFrame, target: float = .15, buffer: float = .1, cols=None,
             cost_mult: float = 1.0, idm: float = 2.0) -> pd.DataFrame:
    """Daily excess returns on capital (T-bill interest on collateral is NOT included)."""
    cols = list(cols or fc.columns)
    w = weights(d, cols)
    pv = (d.vol / d.price.shift(0)).where(d.price > 0)  # daily vol as a fraction of notional
    tgt = (fc[cols] * (target / 16) / pv[cols]).mul(w) * idm  # notional weight
    tgt = tgt.clip(-3, 3).where(fc[cols].notna())
    A = tgt.to_numpy(); H = np.zeros_like(A)
    for j in range(A.shape[1]):
        p = 0.0
        for i in range(A.shape[0]):
            a = A[i, j]
            if np.isnan(a):
                p = 0.0
            elif abs(a - p) > buffer * max(abs(a), 1e-9):
                p = a
            H[i, j] = p
    pos = pd.DataFrame(H, index=tgt.index, columns=cols).shift(1).fillna(0)  # traded at next close
    gross = (pos.shift(1) * d.ret[cols].fillna(0)).sum(axis=1)
    frac = (d.cost[cols] / d.price[cols]).where(d.price[cols] > 0).ffill()
    costs = (pos.diff().abs() * frac * cost_mult).sum(axis=1)
    return pd.DataFrame({"gross": gross, "cost": costs, "net": gross - costs, "turn": pos.diff().abs().sum(axis=1)})


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    if len(x) < 20 or x.std() == 0:
        return {"ret": np.nan, "vol": np.nan, "sharpe": np.nan, "dd": np.nan, "t": np.nan}
    eq = (1 + x).cumprod()
    yrs = len(x) / 256
    sh = x.mean() / x.std() * 16
    return {"ret": eq.iloc[-1] ** (1 / yrs) - 1, "vol": x.std() * 16, "sharpe": sh,
            "dd": (eq / eq.cummax() - 1).min(), "t": sh * np.sqrt(yrs)}


def window(x, name: str):
    a, z = WINDOWS[name]
    return x.loc[a:z]
