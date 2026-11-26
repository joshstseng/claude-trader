"""Black-Scholes in numpy (European, no dividends: prices are dividend-adjusted)."""
from __future__ import annotations
import numpy as np
_a = (0.31938153, -0.356563782, 1.781477937, -1.821255978, 1.330274429)
def N(x):
    x = np.asarray(x, dtype=float); y = np.abs(x); k = 1 / (1 + .2316419 * y)
    p = np.exp(-.5 * y * y) / np.sqrt(2 * np.pi) * sum(c * k ** (i + 1) for i, c in enumerate(_a))
    return np.where(x >= 0, 1 - p, p)
def price(S, K, T, r, iv, put=True):
    S, K, T, iv = map(lambda z: np.maximum(np.asarray(z, dtype=float), 1e-9), (S, K, T, iv))
    v = iv * np.sqrt(T); d1 = (np.log(S / K) + (r + .5 * iv * iv) * T) / v; d2 = d1 - v
    return K * np.exp(-r * T) * N(-d2) - S * N(-d1) if put else S * N(d1) - K * np.exp(-r * T) * N(d2)
def delta(S, K, T, r, iv, put=True):
    S, K, T, iv = map(lambda z: np.maximum(np.asarray(z, dtype=float), 1e-9), (S, K, T, iv))
    d1 = (np.log(S / K) + (r + .5 * iv * iv) * T) / (iv * np.sqrt(T))
    return N(d1) - 1 if put else N(d1)
def implied(px, S, K, T, r, put=True, n=45):
    px, S, K, T = map(lambda z: np.asarray(z, dtype=float), (px, S, K, T))
    lo, hi = np.full(px.shape, .01), np.full(px.shape, 6.0)
    for _ in range(n):
        m = (lo + hi) / 2; high = price(S, K, T, r, m, put) > px
        hi = np.where(high, m, hi); lo = np.where(high, lo, m)
    iv = (lo + hi) / 2
    return np.where((iv < .02) | (iv > 5.9), np.nan, iv)
def strike_for_delta(S, T, r, iv, target, put=True):
    """Strike with |delta| = target at this IV."""
    from math import sqrt
    lo, hi = (S * .2, S * 1.05) if put else (S * .95, S * 3)
    for _ in range(40):
        K = (lo + hi) / 2; d = abs(float(delta(S, K, T, r, iv, put)))
        if put: lo, hi = (K, hi) if d < target else (lo, K)
        else: lo, hi = (K, hi) if d > target else (lo, K)
    return (lo + hi) / 2
