"""Audit of the 15-minute FVG early exit. Written separately from x80 and built candle by candle, so it cannot see future bars."""
import numpy as np
import pandas as pd

from app.research.swing.intraday import load, noise, sharpe
from app.research.swing.v1x import bands, rng, score
from app.research.swing.x24_real import nsx

CH = set(range(5, 76, 6))


def sim(s, U, D, a, z, early=True, n=3, trail=True, block_after=True, delay=1, bps=.6, capital=None, slip=1.0, rand_p=None, rng_=None, split=False):
    out = np.zeros(len(s.days)); longs = np.zeros(len(s.days)); shorts = np.zeros(len(s.days)); hist = []; lo = hi = np.nan; ex_n = pos_n = tr = 0; cc = slip * .5 + .75
    for i in range(max(0, a - 20), z):
        live = i >= max(a, 14) and np.isfinite(s.vol[i]) and s.vol[i] > 0 and np.isfinite(s.prev[i]); w = min(2., .01 / s.vol[i]) if live else 0; ct = 0
        if live and capital:
            ct = int(np.floor(w * capital / (s.o[i, 0] * 2))); live = ct >= 1
        side, en, day, fix, blk = 0, 0., 0., np.nan, 0

        def pl(sd, x):
            return (sd * (x - en) * 2 * ct - cc * ct) / capital if capital else sd * (x / en - 1) * w - bps / 1e4 * w

        for b in range(78):
            if (b + 1) % n == 0:
                k = b - n + 1; cur = (s.h[i, k:b + 1].max(), s.l[i, k:b + 1].min()); hist.append(cur)
                if len(hist) >= 3:
                    h2, l2 = hist[-3]
                    if cur[1] > h2 and h2 < s.c[i, b]:
                        lo = h2
                    if cur[0] < l2 and l2 > s.c[i, b]:
                        hi = l2
                hist = hist[-3:]
            if not live or b < 5 or b > 76:
                continue
            c = s.c[i, b]; f = s.o[i, min(b + delay, 77)]; ex = False
            if side and early and (b + 1) % n == 0:
                pos_n += 1
                if rand_p is not None:
                    ex = rng_.random() < rand_p
                else:
                    lv = (lo if side > 0 else hi) if trail else fix
                    ex = np.isfinite(lv) and (c < lv if side > 0 else c > lv)
            want = None
            if b in CH:
                want = 1 if c > U[i, b] else -1 if c < D[i, b] else 0
                if want == 0 or want == -blk:
                    blk = 0
                if ex and want == side and not block_after:
                    ex = False
            if ex:
                r = pl(side, f); day += r; (longs if side > 0 else shorts)[i] += r; ex_n += 1
                if block_after:
                    blk = side
                side = 0
            if want is not None:
                if side and want != side:
                    r = pl(side, f); day += r; (longs if side > 0 else shorts)[i] += r; side = 0
                if not side and want and want != blk:
                    side, en = want, f; tr += 1; q = -(cc * ct / capital if capital else bps / 1e4 * w); day += q; (longs if side > 0 else shorts)[i] += q
                    lv = lo if side > 0 else hi; fix = lv if np.isfinite(lv) and (lv < en if side > 0 else lv > en) else np.nan
        if side:
            r = pl(side, s.c[i, 77]); day += r; (longs if side > 0 else shorts)[i] += r
        out[i] = day
    return (out, tr, ex_n, pos_n, longs, shorts) if split else (out, tr, ex_n, pos_n)


if __name__ == "__main__":
    q = load("QQQ"); UQ, DQ = bands(q); n = nsx(); UN, DN = bands(n)
    print("1. Control and independent rewrite")
    for w in ("dev", "val", "final"):
        a, z = rng(q, w); b = sim(q, UQ, DQ, a, z, early=False)[0][a:z]; o = noise(q, a, z, look=14, every=6, vm=1.0)[0][a:z]; x = sim(q, UQ, DQ, a, z)[0][a:z]; m = score(x)
        print(f"  {w:<6} no-early control differs from v1 on {(np.abs(b-o) > 1e-9).sum()} days | FVG exit {m['ret']:.2f}%/yr Sharpe {m['sharpe']:.2f} drop {m['dd']:.1f}% worst day {x.min()*100:.2f}%")

    print("\n2. Whole MNQ contracts on Nasdaq-100 index prices")
    print(f"  {'size':>9}{'period':>11}{'v1 %/yr':>9}{'Sh':>6}{'DD%':>7}{'FVG %/yr':>10}{'Sh':>6}{'DD%':>7}{'worst day':>10}{'2 ticks':>9}{'4 ticks':>9}")
    for cap in (50000, 100000, 250000):
        for lab, x0, x1 in (("2020-22", "2020-01-01", "2022-12-31"), ("2023-26", "2023-01-01", "2026-10-31")):
            a, z = int(n.days.searchsorted(pd.Timestamp(x0))), int(n.days.searchsorted(pd.Timestamp(x1), side="right"))
            v = score(sim(n, UN, DN, a, z, early=False, capital=cap)[0][a:z]); r = sim(n, UN, DN, a, z, capital=cap)[0][a:z]; f = score(r); t2 = score(sim(n, UN, DN, a, z, capital=cap, slip=2)[0][a:z]); t4 = score(sim(n, UN, DN, a, z, capital=cap, slip=4)[0][a:z])
            print(f"  {cap:>9,}{lab:>11}{v['ret']:9.1f}{v['sharpe']:6.2f}{v['dd']:7.1f}{f['ret']:10.1f}{f['sharpe']:6.2f}{f['dd']:7.1f}{r.min()*100:10.2f}{t2['ret']:9.1f}{t4['ret']:9.1f}")

    A0, _ = rng(q, "val"); _, Z0 = rng(q, "final"); B0 = sim(q, UQ, DQ, A0, Z0, early=False)[0][A0:Z0]; F = sim(q, UQ, DQ, A0, Z0, split=True); X0 = F[0][A0:Z0]
    print(f"\n3. Slower fills and costs, QQQ 2020-Oct 2026 (v1 Sharpe {sharpe(B0):.2f}, {B0.mean()*252*100:.1f}%/yr)")
    for d, c in ((1, .6), (2, .6), (3, .6), (1, 1.5), (2, 1.5), (1, 3.0)):
        x = sim(q, UQ, DQ, A0, Z0, delay=d, bps=c)[0][A0:Z0]; y = sim(q, UQ, DQ, A0, Z0, early=False, delay=d, bps=c)[0][A0:Z0]
        print(f"  fill delay {(d-1)*5:>2} min, {c} bp: FVG {x.mean()*252*100:5.1f}%/yr Sharpe {sharpe(x):5.2f} | v1 {y.mean()*252*100:5.1f}%/yr Sharpe {sharpe(y):5.2f}")

    print("\n4. Nearby settings, QQQ 2020-Oct 2026")
    for nn in (2, 3, 4, 6):
        for tr in (True, False):
            for bl in (True, False):
                x = sim(q, UQ, DQ, A0, Z0, n=nn, trail=tr, block_after=bl)[0][A0:Z0]; print(f"  FVG {nn*5:>2}m {'trail' if tr else 'fixed'} {'block' if bl else 're-enter'}: {x.mean()*252*100:5.1f}%/yr Sharpe {sharpe(x):5.2f}")

    print("\n5. Placebo: random early exits at the same frequency")
    p = F[2] / max(F[3], 1); g = np.random.default_rng(9); P = np.array([sharpe(sim(q, UQ, DQ, A0, Z0, rand_p=p, rng_=g)[0][A0:Z0]) for _ in range(200)])
    print(f"  exit chance per 15m check {p:.1%}. FVG Sharpe {sharpe(X0):.2f}; random median {np.median(P):.2f}, 95th percentile {np.percentile(P,95):.2f}, max {P.max():.2f}; share at or above FVG {np.mean(P >= sharpe(X0)):.1%}")

    print("\n6. Trade profile, QQQ 2020-Oct 2026")
    i = q.days[A0:Z0]; l, h = F[4][A0:Z0], F[5][A0:Z0]; print(f"  trades {F[1]}, early exits {F[2]} ({F[2]/F[1]:.0%}); longs {l.mean()*252*100:.1f}%/yr Sharpe {sharpe(l):.2f}; shorts {h.mean()*252*100:.1f}%/yr Sharpe {sharpe(h):.2f}")
    print("  by year FVG/v1 %:", {int(y): (round(X0[i.year == y].sum()*100, 1), round(B0[i.year == y].sum()*100, 1)) for y in sorted(set(i.year))})
    o = np.sort(X0)[::-1]; print(f"  top 10 days {o[:10].sum()/o.sum():.0%} of profit (v1 {np.sort(B0)[::-1][:10].sum()/B0.sum():.0%}); worst day {X0.min()*100:.2f}% (v1 {B0.min()*100:.2f}%)")
