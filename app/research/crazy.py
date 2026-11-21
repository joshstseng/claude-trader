"""Crazy Snap variants. One flexible daily engine: entry at the next open after a signal; stop k×ATR; exits by
rule. Same-day stop and target: stop first (conservative). 1% risk sizing to the initial stop (or to a nominal
3×ATR when there's no stop), notional capped at 2× the account, 1 bp slippage each way."""
import sys
sys.path.insert(0, '.')
from app.research import data
from app.research.daily import sma, rsi, atr
from app.research.evaluate import Trade, ACCOUNT, RISK, stats, verdict

U = ['QQQ', 'SPY', 'IWM', 'DIA']
B = {s: [x for x in data.daily(s, fetch=False) if x.t.date().isoformat() <= '2026-10-30'] for s in U}
IND = {}
for s, b in B.items():
    c = [x.c for x in b]
    IND[s] = dict(c=c, r=rsi(c, 2), s200=sma(c, 200), s5=sma(c, 5), s10=sma(c, 10), s20=sma(c, 20), a=atr(b))
SLIP = 1e-4


def ibs(x):
    return (x.c - x.l) / (x.h - x.l) if x.h > x.l else 0.5


def snap_entry(s, i, rsi_th=10, ibs_th=0.1, trend='up'):
    d, x = IND[s], B[s][i]
    if d['s200'][i] is None or d['r'][i] is None:
        return False
    up = d['c'][i] > d['s200'][i]
    if trend == 'up' and not up:
        return False
    if trend == 'down' and up:
        return False
    return d['r'][i] < rsi_th or ibs(x) < ibs_th


def engine(entry, *, side=1, k_stop=3.0, use_stop=True, target_r=None, exit_rule='sma5', trail=None,
           max_days=20, scale_in=False):
    T = []
    for s in U:
        b, d = B[s], IND[s]
        i = 0
        while i < len(b) - 2:
            if d['a'][i] is None or not entry(s, i):
                i += 1
                continue
            k = i + 1
            e = b[k].o * (1 + SLIP * side)
            dist = k_stop * d['a'][i]
            stop = e - side * dist if use_stop else None
            qty = min(RISK * ACCOUNT / dist, 2 * ACCOUNT / e)
            tgt = e + side * target_r * dist if target_r else None
            best = e
            j, px = k, None
            adds = 0
            while j < len(b):
                x = b[j]
                if stop is not None and ((x.l <= stop) if side > 0 else (x.h >= stop)):
                    px = (min(x.o, stop) if side > 0 else max(x.o, stop)) if j > k or True else stop
                    break
                if tgt is not None and ((x.h >= tgt) if side > 0 else (x.l <= tgt)):
                    px = (max(x.o, tgt) if side > 0 else min(x.o, tgt))
                    break
                best = max(best, x.h) if side > 0 else min(best, x.l)
                if isinstance(trail, (int, float)) or trail in ('atr2', 'atr1'):   # chandelier trail from the best price
                    m = trail if isinstance(trail, (int, float)) else (2.0 if trail == 'atr2' else 1.0)
                    lvl = best - side * m * d['a'][j]
                    if stop is None or ((lvl > stop) if side > 0 else (lvl < stop)):
                        stop = lvl
                elif trail == 'prevlow':                              # trail to the prior day's low
                    lvl = x.l if side > 0 else x.h
                    if j > k and (stop is None or ((lvl > stop) if side > 0 else (lvl < stop))):
                        stop = lvl
                elif trail == 'be1r':                                 # break-even after +1R
                    if (best - e) * side >= dist and ((e > stop) if side > 0 else (e < stop)):
                        stop = e
                if scale_in and adds == 0 and j > k and entry(s, j):  # buy again on a fresh signal
                    q2 = qty
                    e = (e * qty + x.c * q2) / (qty + q2)
                    qty += q2
                    adds = 1
                c = d['c']
                done = False
                if exit_rule == 'sma5':
                    done = c[j] > d['s5'][j] if side > 0 else c[j] < d['s5'][j]
                elif exit_rule == 'sma10':
                    done = c[j] > d['s10'][j]
                elif exit_rule == 'sma20':
                    done = c[j] > d['s20'][j]
                elif exit_rule == 'upclose':
                    done = c[j] > c[j - 1]
                elif exit_rule == 'profit':
                    done = (c[j] - e) * side > 0
                elif exit_rule == 'rsi70':
                    done = d['r'][j] > 70
                elif exit_rule == 'none':
                    done = False
                elif exit_rule.startswith('days'):
                    done = j - k + 1 >= int(exit_rule[4:])
                if done or j - i >= max_days:
                    if j + 1 < len(b):
                        j += 1
                        px = b[j].o
                    else:
                        px = c[j]
                    break
                if j == len(b) - 1:
                    px = c[j]
                    break
                j += 1
            T.append(Trade(s, side, b[k].t, b[j].t, e, px * (1 - SLIP * side), qty))
            i = j
    return T


def show(name, T):
    tr, te, al, pre = (stats(T, a, z) for a, z in ((2021, 2023), (2024, 2026), (2016, 2026), (2016, 2020)))
    wins = sum(t.pnl > 0 for t in T)
    pos = sum(v > 0 for v in al.years.values())
    print(f"{name[:48]:48} n={al.n:4} win {wins / max(1, al.n) * 100:3.0f}% PF {al.pf:4.2f} ${al.pnl / 1000:+6.1f}k "
          f"DD ${al.max_dd / 1000:+5.1f}k yrs+ {pos}/{len(al.years)} | PF 16-20 {pre.pf:4.2f} 21-23 {tr.pf:4.2f} 24-26 {te.pf:4.2f}")
    return T
