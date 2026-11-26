"""Swing v1 engine with configurable check times, exits and day filters. Default settings reproduce v1 exactly."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.research.swing.intraday import Sess, load, sharpe

W = {"dev": ("2016-01-01", "2019-12-31"), "val": ("2020-01-01", "2022-12-31"), "final": ("2023-01-01", "2026-10-31")}


@dataclass(frozen=True)
class X:
    every: int = 6; first: int = 5; exit: str = "band"; k: float = 0.0; label: str = "Swing v1"


def vwap(s: Sess):
    v = np.maximum(s.v, 1); tp = (s.h + s.l + s.c) / 3
    return np.cumsum(tp * v, axis=1) / np.cumsum(v, axis=1)


def bands(s: Sess, look=14):
    mv = np.abs(s.c / s.o[:, 0, None] - 1); U = np.full(s.c.shape, np.nan); D = U.copy()
    for i in range(look, len(s.days)):
        if np.isfinite(s.prev[i]):
            g = np.nanmean(mv[i - look:i], axis=0); U[i] = max(s.o[i, 0], s.prev[i]) * (1 + g); D[i] = min(s.o[i, 0], s.prev[i]) * (1 - g)
    return U, D


def run(s: Sess, x: X, a: int, z: int, U, D, VW, bps=.6, skip=None, only=None, start_bar=None):
    """skip/only are boolean arrays by day. start_bar optionally delays the first check on a day."""
    out = np.zeros(len(s.days)); tr = 0; ch = list(range(x.first, 76, x.every))
    for i in range(max(a, 14), z):
        v = s.vol[i]
        if not np.isfinite(v) or v <= 0 or not np.isfinite(s.prev[i]) or (skip is not None and skip[i]) or (only is not None and not only[i]):
            continue
        w = min(2.0, .01 / v); side, en, day, best = 0, 0.0, 0.0, 0.0; cool = 0; c_ = s.c[i]; u_ = U[i]; d_ = D[i]; vw = VW[i]; o_ = s.o[i]
        first = -1 if start_bar is None else int(start_bar[i])
        for b in ch:
            if b < first:
                continue
            c = c_[b]; u = u_[b]; d = d_[b]; m = vw[b]; f = o_[b + 1]
            up = c > max(u, m) if x.exit in ("tight", "vwap") else c > u
            dn = c < min(d, m) if x.exit in ("tight", "vwap") else c < d
            want = 1 if up else -1 if dn else 0
            if d <= c <= u:
                cool = 0
            if side:
                best = max(best, c) if side > 0 else min(best, c)
                if x.exit == "band":
                    out_ = c <= u if side > 0 else c >= d
                elif x.exit == "tight":
                    out_ = c <= max(u, m) if side > 0 else c >= min(d, m)
                elif x.exit == "vwap":
                    out_ = c <= m if side > 0 else c >= m
                elif x.exit == "loose":
                    out_ = c <= min(u, m) if side > 0 else c >= max(d, m)
                elif x.exit == "opposite":
                    out_ = c < d if side > 0 else c > u
                elif x.exit == "close":
                    out_ = False
                else:
                    gap = x.k * v * c
                    out_ = c <= best - gap if side > 0 else c >= best + gap
                if out_:
                    day += side * (f / en - 1) * w - bps / 1e4 * w
                    if x.exit.startswith("trail"):
                        cool = side
                    side = 0
            if not side and want and want != cool:
                side, en, best = want, f, c; day -= bps / 1e4 * w; tr += 1
        if side:
            day += side * (c_[77] / en - 1) * w - bps / 1e4 * w
        out[i] = day
    return out, tr


def rng(s, w):
    return int(s.days.searchsorted(pd.Timestamp(W[w][0]))), int(s.days.searchsorted(pd.Timestamp(W[w][1]), side="right"))


def score(x):
    e = np.cumsum(x)
    return dict(ret=float(np.mean(x) * 252 * 100), sharpe=sharpe(x), dd=float((e - np.maximum.accumulate(e)).min() * 100))


def gates(s, group, cands, U, D, VW):
    """cands: list of (label, X, run kwargs). Applies FROZEN_V1X.md and prints the outcome."""
    base = {w: score(run(s, X(), *rng(s, w), U, D, VW)[0][rng(s, w)[0]:rng(s, w)[1]]) for w in W}
    a, z = rng(s, "dev"); rows = []
    for lab, x_, kw in cands:
        r, t = run(s, x_, a, z, U, D, VW, **kw); r2, _ = run(s, x_, a, z, U, D, VW, bps=1.2, **kw); m = score(r[a:z]); m2 = score(r2[a:z]); rows.append((lab, x_, kw, m, m2, t))
    print(f"\n=== {group}: v1 2016-19 {base['dev']['ret']:.1f}%/yr, Sharpe {base['dev']['sharpe']:.2f}, worst drop {base['dev']['dd']:.1f}%")
    for lab, _, _, m, m2, t in sorted(rows, key=lambda q: -q[3]["sharpe"]):
        print(f"  {lab:<36}{m['ret']:6.1f}%/yr  Sharpe {m['sharpe']:5.2f}  drop {m['dd']:6.1f}%  2x cost {m2['ret']:5.1f}%  trades {t}")
    el = [q for q in rows if q[3]["sharpe"] > base["dev"]["sharpe"] and q[4]["ret"] > 0 and q[5] >= 100]
    if not el:
        print("  No variant beat v1 on 2016-2019, so no later data was run."); return None
    lab, x_, kw, _, _, _ = max(el, key=lambda q: q[3]["sharpe"]); a, z = rng(s, "val"); v = score(run(s, x_, a, z, U, D, VW, **kw)[0][a:z])
    print(f"  Finalist: {lab}\n  2020-22: {v['ret']:.1f}%/yr Sharpe {v['sharpe']:.2f} drop {v['dd']:.1f}% | v1 {base['val']['ret']:.1f}%/yr {base['val']['sharpe']:.2f} {base['val']['dd']:.1f}%")
    if v["sharpe"] <= base["val"]["sharpe"]:
        print("  FAILED the 2020-22 gate. Final not run."); return lab, "failed val"
    a, z = rng(s, "final"); f = score(run(s, x_, a, z, U, D, VW, **kw)[0][a:z]); f2 = score(run(s, x_, a, z, U, D, VW, bps=1.2, **kw)[0][a:z]); ok = f["sharpe"] > base["final"]["sharpe"] and f["ret"] > base["final"]["ret"] and f2["ret"] > 0
    print(f"  2023-Oct 26: {f['ret']:.1f}%/yr Sharpe {f['sharpe']:.2f} drop {f['dd']:.1f}% | 2x cost {f2['ret']:.1f}% | v1 {base['final']['ret']:.1f}%/yr {base['final']['sharpe']:.2f} {base['final']['dd']:.1f}% -> {'PASS' if ok else 'FAIL'}")
    return lab, "pass" if ok else "failed final"
