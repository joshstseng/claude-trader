"""Whole-contract simulator for the trend sleeve using micro or mini contract sizes."""
import numpy as np
import pandas as pd

from app.research.swing.lab import ewmac, weights

# dollars per price point for the smallest practical CME-group contract
MULT = {"SP500": 5, "NASDAQ": 2, "RUSSELL": 5, "DOW": .5, "GOLD": 10, "SILVER": 1000, "COPPER": 2500, "CRUDE_W": 100, "EUR": 12500, "GBP": 6250,
        "AUD": 10000, "JPY": 1250000, "CAD": 10000, "CHF": 12500, "US10": 150, "CORN": 10, "SOYBEAN": 10, "WHEAT": 10}
FEE = 1.50  # commission and exchange fee per contract per side


def trend(d):
    return pd.concat([ewmac(d, n) for n in (16, 32, 64)]).groupby(level=0).mean()


def run(d, capital, cols, target=.15, idm=2.0, buffer=.25, cost_mult=1.0, start="1985-01-01", end="2018-12-31", spread=None):
    f = trend(d)[cols].loc[start:end]; w = weights(d, cols)
    px, adj, vol = (x[cols].reindex(f.index) for x in (d.price, d.adj, d.vol))
    m = pd.Series(MULT)[cols]
    sp = (d.cost[cols] if spread is None else spread[cols]).to_numpy()
    F, P, A, V = f.to_numpy(), px.to_numpy(), adj.to_numpy(), vol.to_numpy()
    n, k = F.shape; H = np.zeros(k); eq = capital; out = np.zeros(n); pending = np.zeros(k); contracts = np.zeros((n, k))
    W, M = w[cols].to_numpy(), m.to_numpy()
    for i in range(1, n):
        dA = np.nan_to_num(A[i] - A[i - 1])
        pnl = float((H * dA * M).sum())
        trade = pending - H
        c = float((np.abs(trade) * (sp * M * cost_mult + FEE)).sum())
        # the order decided yesterday fills at today's close, after today's P&L on the old position
        H = pending.copy(); out[i] = (pnl - c) / capital  # sized on fixed capital, so account size stays honest
        tgt = np.nan_to_num(F[i] * (target / 16) * capital * W * idm / (V[i] * M))
        new = pending.copy()
        for j in range(k):
            if np.isnan(F[i, j]) or np.isnan(V[i, j]):
                new[j] = 0
            elif round(tgt[j]) != H[j] and abs(tgt[j] - H[j]) > max(buffer * abs(tgt[j]), .6):
                new[j] = round(tgt[j])
        pending = new; contracts[i] = H
    return pd.Series(out, index=f.index), pd.DataFrame(contracts, index=f.index, columns=cols)
