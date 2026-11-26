"""Swing v2 simulator: v1's 30-minute signal and exits, with a lower-timeframe pullback entry.

Indicators are computed only from completed bars. Oscillator entries fill at the next bar's open.
Limit entries need price to trade 0.2 bp through the level, and fill at the level or a worse open.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.research.swing.intraday import Sess, load

THROUGH = 2e-5
CHECKS = list(range(5, 76, 6))


@dataclass
class TF:
    step: int; days: pd.DatetimeIndex; o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; v: np.ndarray
    U: np.ndarray; D: np.ndarray; sig: np.ndarray; w: np.ndarray; rsi: dict; ema: dict; vwap: np.ndarray; base: Sess


def rsi_flat(c, n):
    x = c.ravel(); d = np.diff(x, prepend=x[0]); a = 1 / n
    up = pd.Series(np.maximum(d, 0)).ewm(alpha=a, adjust=False).mean().to_numpy(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=a, adjust=False).mean().to_numpy()
    with np.errstate(all="ignore"):
        r = 100 * up / (up + dn)
    return np.nan_to_num(r, nan=50.).reshape(c.shape)


def ema_flat(c, n):
    return pd.Series(c.ravel()).ewm(span=n, adjust=False).mean().to_numpy().reshape(c.shape)


def build(step: int, npz="data/bars/lab/intraday/alpaca/QQQ_1m.npz", base: Sess | None = None, look=14) -> TF:
    z = np.load(npz, allow_pickle=False); d1 = pd.DatetimeIndex(z["days"]); q = base or load("QQQ")
    common = q.days.intersection(d1); a = q.days.get_indexer(common); b = d1.get_indexer(common)
    C = pd.DataFrame(z["c"][b]).ffill(axis=1).bfill(axis=1).to_numpy()
    O = np.where(np.isnan(z["o"][b]), C, z["o"][b]); H = np.where(np.isnan(z["h"][b]), C, z["h"][b]); L = np.where(np.isnan(z["l"][b]), C, z["l"][b]); V = np.nan_to_num(z["v"][b].astype(float))
    n = 390 // step; r = lambda x, f: np.column_stack([f(x[:, t * step:(t + 1) * step], axis=1) for t in range(n)])
    if step == 1:
        o, h, l, c, v = O, H, L, C, V
    else:
        o, c = O[:, ::step], C[:, step - 1::step]; h, l, v = r(H, np.max), r(L, np.min), r(V, np.sum)
    N = len(common); mv = np.abs(q.c / q.o[:, 0, None] - 1); U5 = np.full((len(q.days), 78), np.nan); D5 = U5.copy()
    for i in range(look, len(q.days)):
        if np.isfinite(q.prev[i]):
            s = np.nanmean(mv[i - look:i], axis=0); U5[i] = max(q.o[i, 0], q.prev[i]) * (1 + s); D5[i] = min(q.o[i, 0], q.prev[i]) * (1 - s)
    idx = (np.arange(n) * step) // 5; U, D = U5[a][:, idx], D5[a][:, idx]
    sig = np.zeros((N, len(CHECKS)), int); U5a, D5a, c5 = U5[a], D5[a], q.c[a]
    for j, k in enumerate(CHECKS):
        sig[:, j] = np.where(c5[:, k] > U5a[:, k], 1, np.where(c5[:, k] < D5a[:, k], -1, 0))
    vv = np.maximum(v, 1); tp = (h + l + c) / 3; vw = np.cumsum(tp * vv, axis=1) / np.cumsum(vv, axis=1)
    w = np.where(np.isfinite(q.vol[a]) & (q.vol[a] > 0) & np.isfinite(U5a[:, 0]), np.minimum(2.0, .01 / np.where(q.vol[a] > 0, q.vol[a], 1)), 0.0)
    return TF(step, common, o, h, l, c, v, U, D, sig, w, {m: rsi_flat(c, m) for m in (2, 7, 14)}, {m: ema_flat(c, m) for m in (9, 20)}, vw, q)


@dataclass(frozen=True)
class Spec:
    kind: str; wait: int; expiry: str; n: int = 2; lvl: float = 10; level: str = "band"; fib: float = .5

    @property
    def group(self):
        return {"osc": "oscillator", "rev": "reversal", "lim": "limit", "now": "control"}[self.kind]

    @property
    def name(self):
        t = {"osc": f"RSI{self.n}<{self.lvl:g}", "rev": "RSI2<20 + reversal bar", "now": "Swing v1 entry"}.get(self.kind) or (f"{self.fib:.1%} retrace" if self.level == "fib" else f"touch {self.level}")
        return f"{t}, wait {self.wait}m, {self.expiry}"


def scan(T: TF, i: int, sd: int, start: int, stop: int, chk: int, sp: Spec):
    """First entry in bars start..stop, where chk is the signal bar. Returns (bar, price) or None."""
    last = T.o.shape[1] - 1; stop = min(stop, last)
    if stop < start:
        return None
    if sp.kind == "osc":
        r = T.rsi[sp.n][i]; cl = T.c[i]
        hit = (r < sp.lvl) & (cl > T.U[i]) if sd > 0 else (r > 100 - sp.lvl) & (cl < T.D[i])
        x = np.flatnonzero(hit[start:stop])  # the signal bar must close before the fill bar
        return None if not len(x) else (start + int(x[0]) + 1, float(T.o[i, start + int(x[0]) + 1]))
    if sp.kind == "rev":
        r = T.rsi[2][i]; os_ = r < 20 if sd > 0 else r > 80; y = np.flatnonzero(os_[start:stop])
        if not len(y):
            return None
        a = start + int(y[0]) + 1; c = T.c[i]; prior = np.r_[np.nan, T.h[i, :-1]] if sd > 0 else np.r_[np.nan, T.l[i, :-1]]
        ok = (c > prior) & (c > T.U[i]) if sd > 0 else (c < prior) & (c < T.D[i])
        x = np.flatnonzero(ok[a:stop])
        return None if not len(x) else (a + int(x[0]) + 1, float(T.o[i, a + int(x[0]) + 1]))
    if sp.level == "fib":
        k = max(0, chk + 1 - 30 // T.step); c0 = T.c[i, chk]
        ref = T.l[i, k:chk + 1].min() if sd > 0 else T.h[i, k:chk + 1].max()
        lv = np.full(stop + 1, c0 - sd * sp.fib * abs(c0 - ref))
    elif sp.level == "band":
        lv = T.U[i] if sd > 0 else T.D[i]
    elif sp.level == "vwap":
        lv = np.r_[np.nan, T.vwap[i, :-1]]
    else:
        lv = np.r_[np.nan, T.ema[int(sp.level[3:])][i, :-1]]
    lvl = lv[start:stop + 1]
    hit = T.l[i, start:stop + 1] <= lvl * (1 - THROUGH) if sd > 0 else T.h[i, start:stop + 1] >= lvl * (1 + THROUGH)
    x = np.flatnonzero(hit)
    if not len(x):
        return None
    b = start + int(x[0]); L = float(lv[b])
    return b, min(L, float(T.o[i, b])) if sd > 0 else max(L, float(T.o[i, b]))


def run(T: TF, sp: Spec, a: int, z: int, bps=.6, mult=1.0):
    out = np.zeros(len(T.days)); trades = 0; skipped = 0; cost = bps * mult / 1e4; st = T.step; bars = T.o.shape[1]
    wait = max(1, sp.wait // st) if sp.kind != "now" else 0; chks = [(k + 1) * 5 // st - 1 for k in CHECKS]
    for i in range(a, z):
        w = T.w[i]
        if w <= 0:
            continue
        side, en, day = 0, 0.0, 0.0; arm = None; cool = set()

        def try_fill(upto):
            nonlocal side, en, day, arm, trades, skipped, cool
            if arm is None or side:
                return
            sd, start, sigbar = arm; e = start + wait
            f = scan(T, i, sd, start, min(upto, e - 1), sigbar, sp)
            if f is not None:
                side, en = sd, f[1]; day -= cost * w; trades += 1; arm = None; return
            if e <= upto and e < bars:
                if sp.expiry == "market":
                    side, en = sd, float(T.o[i, e]); day -= cost * w; trades += 1
                else:
                    skipped += 1; cool.add(sd)
                arm = None

        for j, ck in enumerate(chks):
            try_fill(ck)
            want = int(T.sig[i, j]); nx = ck + 1
            if want == 0:
                cool.clear()
            else:
                cool.discard(-want)
            if side and want != side:
                day += side * (T.o[i, nx] / en - 1) * w - cost * w; side = 0
            if arm is not None and want != arm[0]:
                arm = None
            if not side and arm is None and want and want not in cool:
                if sp.kind == "now":
                    side, en = want, float(T.o[i, nx]); day -= cost * w; trades += 1
                else:
                    arm = (want, nx, ck)
        try_fill(bars - 2)
        if side:
            day += side * (T.c[i, -1] / en - 1) * w - cost * w
        out[i] = day
    return out, trades, skipped


def variants():
    S = []
    for wt in (15, 30, 60):
        for ex in ("skip", "market"):
            S += [Spec("osc", wt, ex, n=2, lvl=10), Spec("osc", wt, ex, n=2, lvl=20), Spec("osc", wt, ex, n=7, lvl=30), Spec("osc", wt, ex, n=14, lvl=30), Spec("rev", wt, ex)]
            S += [Spec("lim", wt, ex, level=lv) for lv in ("band", "ema9", "ema20", "vwap")] + [Spec("lim", wt, ex, level="fib", fib=f) for f in (.382, .5, .618)]
    return S
