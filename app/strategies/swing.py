"""Swing v1 and v1.1 rules, with no broker or clock inside.

Swing v1: every 30 minutes on a completed 5-minute bar, be long above the noise band, short below it, flat inside it.
Swing v1.1 adds one exit: when a 15-minute candle closes through the newest same-direction fair value gap, exit and
block that side until a 30-minute check is back inside the band or beyond the opposite band.

A decision on bar b fills at the open of bar b + 1. Everything is flat at the last bar's close.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

BARS = 78
CHECKS = frozenset(range(5, 76, 6))
CANDLE = 3
LOOKBACK = 14


def update_fvg(candles: list, lo, hi, high: float, low: float, close: float):
    """Add one completed 15-minute candle. Returns the newest intact bullish and bearish invalidation levels."""
    candles = [*candles, [float(high), float(low)]]
    if len(candles) >= 3:
        h2, l2 = candles[-3]
        if low > h2 and h2 < close:
            lo = h2
        if high < l2 and l2 > close:
            hi = l2
    return candles[-3:], lo, hi


def context(O: np.ndarray, H: np.ndarray, L: np.ndarray, C: np.ndarray, target: float = .01, cap: float = 2.0) -> dict:
    """Everything known before today's open, from prior full sessions (oldest first, N x 78 arrays)."""
    if len(C) < max(LOOKBACK, 11):
        raise ValueError(f"need at least {max(LOOKBACK, 11)} prior sessions, got {len(C)}")
    closes = pd.Series(C[:, -1])
    vol = float(closes.pct_change().ewm(span=20, min_periods=10).std().iloc[-1])
    if not math.isfinite(vol) or vol <= 0:
        raise ValueError("no usable volatility")
    sigma = np.nanmean(np.abs(C[-LOOKBACK:] / O[-LOOKBACK:, 0, None] - 1), axis=0)
    candles, lo, hi = [], None, None
    for i in range(len(C)):
        for b in range(CANDLE - 1, BARS, CANDLE):
            candles, lo, hi = update_fvg(candles, lo, hi, H[i, b - 2:b + 1].max(), L[i, b - 2:b + 1].min(), C[i, b])
    return {"prev": float(C[-1, -1]), "vol": vol, "weight": min(cap, target / vol), "sigma": [float(x) for x in sigma],
            "candles": candles, "lo": lo, "hi": hi}


@dataclass
class Machine:
    """One strategy's state for one session. It is plain data, so it can be saved and resumed after a restart."""
    up: list
    down: list
    weight: float
    fvg: bool
    lo: float | None = None
    hi: float | None = None
    candles: list = field(default_factory=list)
    side: int = 0
    block: int = 0
    next_bar: int = 0
    signal_bar: int = -1
    why: str = ""
    held: int = 0
    entry: float = 0.0
    pnl: float = 0.0
    trades: int = 0
    cost: float = .6e-4

    @classmethod
    def start(cls, ctx: dict, first_open: float, fvg: bool, cost_bp: float = .6) -> "Machine":
        high, low = max(first_open, ctx["prev"]), min(first_open, ctx["prev"])
        return cls([high * (1 + s) for s in ctx["sigma"]], [low * (1 - s) for s in ctx["sigma"]], ctx["weight"], fvg,
                   ctx["lo"], ctx["hi"], [list(x) for x in ctx["candles"]], cost=cost_bp / 1e4)

    def to_dict(self) -> dict:
        return asdict(self)

    def step(self, b: int, O, H, L, C) -> bool:
        """Process completed bar b once. Returns True if the wanted position changed."""
        if b != self.next_bar:
            raise ValueError(f"expected bar {self.next_bar}, got {b}")
        self.next_bar = b + 1
        if self.held != self.side:          # the model fills the previous bar's decision at this bar's open
            if self.held:
                self.pnl += self.held * (O[b] / self.entry - 1) * self.weight - self.cost * self.weight
                self.held = 0
            if self.side:
                self.held, self.entry, self.trades = self.side, float(O[b]), self.trades + 1
                self.pnl -= self.cost * self.weight
        c = float(C[b])
        fifteen = (b + 1) % CANDLE == 0
        if fifteen:
            self.candles, self.lo, self.hi = update_fvg(self.candles, self.lo, self.hi, max(H[b - 2:b + 1]), min(L[b - 2:b + 1]), c)
        if b == BARS - 1:
            if self.held:
                self.pnl += self.held * (c / self.entry - 1) * self.weight - self.cost * self.weight
            changed = self.side != 0
            self.held = self.side = 0
            self.why = "flat by the close" if changed else self.why
            return changed
        if b < 5 or b > 76:
            return False
        before, ex = self.side, False
        if self.fvg and self.side and fifteen:
            lv = self.lo if self.side > 0 else self.hi
            ex = lv is not None and (c < lv if self.side > 0 else c > lv)
        want = None
        if b in CHECKS:
            want = 1 if c > self.up[b] else -1 if c < self.down[b] else 0
            if want == 0 or want == -self.block:
                self.block = 0
        if ex:
            self.block, self.side, self.why = self.side, 0, "15m close through the FVG"
        if want is not None:
            if self.side and want != self.side:
                self.why = "back inside the band" if want == 0 else "flipped at the opposite band"
                self.side = 0
            if not self.side and want and want != self.block:
                self.side, self.why = want, "breakout above the band" if want > 0 else "breakdown below the band"
        if self.side != before:
            self.signal_bar = b
            return True
        return False
