"""Exploratory: add a resting stop, fixed at entry, to the Nasdaq noise-band rule. Exits at the 30-minute check and the close stay the same.

Modes
  none      original rule (control)
  band      long stop = upper band at the signal check; short stop = lower band at the signal check
  opposite  long stop = lower band at the signal check; short stop = upper band at the signal check

Stops fill at the stop or at a worse bar open. A fill already through the stop exits immediately.
"""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, noise, sharpe, span
from app.research.swing.x24_real import mnq, nsx


def sim(s, a, z, mode="none", reenter=True, bps=.6, capital=None, stop_ticks=0.0, slip_ticks=1.0, look=14):
    out = np.zeros(len(s.days)); mv = np.abs(s.c / s.o[:, 0, None] - 1); n_tr = n_stop = 0; checks = set(range(5, 76, 6)); side_cost = slip_ticks * .25 * 2 + .75
    for i in range(max(a, look), z):
        v = s.vol[i]
        if not np.isfinite(v) or v <= 0 or not np.isfinite(s.prev[i]):
            continue
        w = min(2.0, .01 / v)
        if capital:
            n = int(np.floor(w * capital / (s.o[i, 0] * 2)))
            if n < 1:
                continue

        def leg(sd, e, x, extra=0.0):
            if capital:
                return (sd * (x - e) * 2 * n - side_cost * n - extra * .25 * 2 * n) / capital
            return sd * (x / e - 1) * w - bps / 1e4 * w - extra * .25 / e * w

        def open_cost():
            return -(side_cost * n) / capital if capital else -bps / 1e4 * w

        b_ = np.nanmean(mv[i - look:i], axis=0); U = max(s.o[i, 0], s.prev[i]) * (1 + b_); L = min(s.o[i, 0], s.prev[i]) * (1 - b_)
        side, entry, stop, pending, day = 0, 0.0, np.nan, None, 0.0; blocked = set()
        for b in range(6, 78):
            if pending is not None:
                want, st = pending; pending = None; f = s.o[i, b]
                if side:
                    day += leg(side, entry, f)
                side = want
                if side:
                    entry, stop = f, st; day += open_cost(); n_tr += 1
            if side and mode != "none":
                hit = (side > 0 and s.l[i, b] <= stop) or (side < 0 and s.h[i, b] >= stop)
                if hit:
                    f = min(stop, s.o[i, b]) if side > 0 else max(stop, s.o[i, b])
                    day += leg(side, entry, f, stop_ticks); n_stop += 1
                    if not reenter:
                        blocked.add(side)
                    side = 0
            if b in checks or b == 5:
                c = s.c[i, b]; want = 1 if c > U[b] else -1 if c < L[b] else 0
                if want in blocked:
                    want = 0
                if want != side:
                    st = np.nan if want == 0 else (U[b] if want > 0 else L[b]) if mode == "band" else (L[b] if want > 0 else U[b])
                    pending = (want, st)
        # the first check is on bar 5, before this loop's first bar
        out[i] = day
    return out, n_tr, n_stop


def sim_full(s, a, z, **k):
    """Same as sim, but also evaluates the 10:00 check on bar 5 and the 4:00 exit."""
    mode = k.get("mode", "none"); reenter = k.get("reenter", True); bps = k.get("bps", .6); capital = k.get("capital"); stop_ticks = k.get("stop_ticks", 0.0); slip_ticks = k.get("slip_ticks", 1.0); look = 14
    out = np.zeros(len(s.days)); mv = np.abs(s.c / s.o[:, 0, None] - 1); n_tr = n_stop = 0; side_cost = slip_ticks * .25 * 2 + .75; checks = set(range(5, 76, 6)); wins = []
    for i in range(max(a, look), z):
        v = s.vol[i]
        if not np.isfinite(v) or v <= 0 or not np.isfinite(s.prev[i]):
            continue
        w = min(2.0, .01 / v); n = 0
        if capital:
            n = int(np.floor(w * capital / (s.o[i, 0] * 2)))
            if n < 1:
                continue
        def px(sd, e, x, extra=0.0):
            return (sd * (x - e) * 2 * n - side_cost * n - extra * .5 * n) / capital if capital else sd * (x / e - 1) * w - bps / 1e4 * w - extra * .25 / e * w
        enter = (-(side_cost * n) / capital) if capital else (-bps / 1e4 * w)
        sg = np.nanmean(mv[i - look:i], axis=0); U = max(s.o[i, 0], s.prev[i]) * (1 + sg); L = min(s.o[i, 0], s.prev[i]) * (1 - sg)
        side, entry, stop, pending, day, blocked, tp = 0, 0.0, np.nan, None, 0.0, set(), 0.0
        for b in range(5, 78):
            if pending is not None:
                want, st = pending; pending = None; f = s.o[i, b]
                if side:
                    r = px(side, entry, f); day += r; wins.append(tp + r)
                side = want
                if side:
                    entry, stop, tp = f, st, enter; day += enter; n_tr += 1
            if side and mode != "none" and ((side > 0 and s.l[i, b] <= stop) or (side < 0 and s.h[i, b] >= stop)):
                f = min(stop, s.o[i, b]) if side > 0 else max(stop, s.o[i, b]); r = px(side, entry, f, stop_ticks); day += r; wins.append(tp + r); n_stop += 1
                if not reenter:
                    blocked.add(side)
                side = 0
            if b in checks:
                c = s.c[i, b]; want = 1 if c > U[b] else -1 if c < L[b] else 0
                if want in blocked:
                    want = 0
                if want != side:
                    st = np.nan if want == 0 else ((U[b] if want > 0 else L[b]) if mode == "band" else (L[b] if want > 0 else U[b]))
                    pending = (want, st)
        if side:
            r = px(side, entry, s.c[i, 77]); day += r; wins.append(tp + r)
        out[i] = day
    return out, n_tr, n_stop, np.array(wins)


if __name__ == "__main__":
    q = load("QQQ"); n = nsx()
    a, z = span(q, "dev"); chk = sim_full(q, a, z)[0][a:z]; base = noise(q, a, z, look=14, every=6, vm=1.0)[0][a:z]
    a2, z2 = span(q, "final"); chk2 = sim_full(q, a2, z2)[0][a2:z2]; base2 = noise(q, a2, z2, look=14, every=6, vm=1.0)[0][a2:z2]
    print(f"control check against the frozen rule: dev days differing {(np.abs(chk-base)>1e-9).sum()}, final days differing {(np.abs(chk2-base2)>1e-9).sum()}")
    V = [("Original, no stop", dict(mode="none")), ("SL at entry band, can re-enter", dict(mode="band")), ("SL at entry band, no same-side re-entry", dict(mode="band", reenter=False)),
         ("SL at opposite band, can re-enter", dict(mode="opposite")), ("SL at entry band + 2 ticks stop slip", dict(mode="band", stop_ticks=2.0)), ("SL opposite band + 2 ticks stop slip", dict(mode="opposite", stop_ticks=2.0))]
    for title, S, extra, wins in (("QQQ", q, {}, ("dev", "val", "final")), ("Whole-contract MNQ, $100k", n, dict(capital=100000), ("val", "final"))):
        print(f"\n{title}")
        print(f"{'':<42}" + "".join(f"{w+' %/yr':>12}{'Sh':>6}{'DD%':>7}" for w in wins) + f"{'trades':>8}{'stopped':>8}{'win%':>6}{'worst day%':>11}")
        for name, p in V:
            line = f"{name:<42}"; tt = ts = 0; all_x = []; all_w = []
            for w in wins:
                if S is n and w == "val":
                    aa, zz = 0, int(S.days.searchsorted(pd.Timestamp("2022-12-31"), side="right"))
                elif S is n:
                    aa, zz = int(S.days.searchsorted(pd.Timestamp("2023-01-01"))), len(S.days)
                else:
                    aa, zz = span(S, w)
                x, t, st, wr = sim_full(S, aa, zz, **{**p, **extra}); x = x[aa:zz]; e = x.cumsum(); tt += t; ts += st; all_x.append(x); all_w.append(wr)
                line += f"{x.mean()*252*100:12.1f}{sharpe(x):6.2f}{(e-np.maximum.accumulate(e)).min()*100:7.1f}"
            xx = np.concatenate(all_x); ww = np.concatenate(all_w)
            print(line + f"{tt:8d}{ts:8d}{(ww>0).mean()*100:6.0f}{xx.min()*100:11.2f}")
