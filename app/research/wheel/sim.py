"""Layer C: a daily portfolio wheel on modeled option prices. Decisions use yesterday's close, fills use today's open or
close. Whole contracts, cash-secured, bankrupt stocks go to zero, and the universe is point-in-time."""
from __future__ import annotations
import calendar, math, random
from dataclasses import dataclass, replace
from datetime import date, timedelta
import numpy as np, pandas as pd
from app.research import yahoo
from app.research.wheel import calib
from app.research.wheel.panel import clean

def _N(x): return .5 * math.erfc(-x / 1.4142135623730951)

def bs(S, K, T, r, iv, put):
    if T <= 0: return max(K - S, 0.) if put else max(S - K, 0.)
    v = iv * math.sqrt(T); d1 = (math.log(S / K) + (r + .5 * iv * iv) * T) / v; d2 = d1 - v; D = math.exp(-r * T)
    return K * D * _N(-d2) - S * _N(-d1) if put else S * _N(d1) - K * D * _N(d2)

@dataclass(frozen=True)
class Spec:
    name: str = "base"
    tenor: str = "1m"              # 1w, 1m, 2m
    top_n: int = 200
    n_pos: int = 6
    weight: float = .20
    delta: float = .25
    call_delta: float = .30
    profit: float | None = None    # buy back at this share of the premium captured
    stop: float | None = None      # buy back at this multiple of the premium received
    rank: str = "liq"              # liq, iv, iv_low, rand
    iv_lo: float = 0.
    iv_hi: float = 9.
    trend: bool = False            # the stock must be above its 200-day
    spy_up: bool = False           # new puts only while SPY is above its 200-day
    vix_lo: float = 0.
    vix_hi: float = 999.
    exit_below_200: bool = False   # sell assigned stock when it closes below its 200-day
    exit_loss: float | None = None # sell assigned stock this far below the assignment price
    call_at_basis: bool = False    # never sell a call below the assignment price
    spread: float = .05            # fill this share of the premium worse than the model
    tick: float = .02              # at least this per share, each option trade
    comm: float = .65
    stock_bp: float = 5.
    capital: float = 50_000.
    seed: int = 1
    idle_yield: float = 1.         # share of the T-bill rate earned on cash
    core: str | None = None        # hold idle cash (beyond put collateral) in SPY or QQQ
    core_trend: bool = False       # hold the core only while SPY is above its 200-day
    iv_scale: float = 1.           # multiply modeled IV (calibration sensitivity)
    off_high: float | None = None  # skip stocks more than this far below their 1-year high

class Mkt:
    def __init__(self):
        self.P = P = clean(); self.days = P.days; self.n = len(P.days)
        self.rv20, self.rv60 = calib.features(P); self.vix, self.rf = calib.macro(P.days)
        self.s200 = pd.DataFrame(P.C).rolling(200, min_periods=150).mean().values
        y = {b.t.date(): b for b in yahoo.daily("SPY")}; q = {b.t.date(): b for b in yahoo.daily("QQQ")}
        self.spy = np.array([y[d].c for d in P.days]); self.qqq = np.array([q[d].c if d in q else np.nan for d in P.days])
        self.spy200 = pd.Series(self.spy).rolling(200, min_periods=150).mean().values
        self.mo = [d.strftime("%Y-%m") for d in P.days]; self.months = sorted(set(self.mo))
        last = {}
        for i, m in enumerate(self.mo): last[m] = i
        self.mo_last = last; self.lastdata = {j: int(np.where(~np.isnan(P.C[:, j]))[0][-1]) for j in range(P.C.shape[1]) if (~np.isnan(P.C[:, j])).any()}
        self.cyc = {t: self._cycles(t) for t in ("1w", "1m", "2m")}
        self.beta = calib.fit_final(); self.scale = 1.
        self.hi = pd.DataFrame(P.C).rolling(252, min_periods=120).max().values

    def _idx(self, d):
        i = np.searchsorted(self._ord, d.toordinal(), side="right") - 1
        return int(i)

    def _cycles(self, tenor):
        self._ord = np.array([d.toordinal() for d in self.days]); out = {}
        if tenor == "1w":
            fr = sorted({self._idx(d + timedelta(days=(4 - d.weekday()) % 7)) for d in self.days})
            for a, b in zip(fr, fr[1:]):
                if a + 1 < b: out[a + 1] = b
            return out
        ex = []; y, m = 2015, 1
        while (y, m) <= (2026, 11):
            d = date(y, m, 1); d += timedelta(days=(4 - d.weekday()) % 7); d += timedelta(days=14)
            if d <= self.days[-1]: ex.append(self._idx(d))
            y, m = (y + (m == 12), 1 if m == 12 else m + 1)
        step = 1 if tenor == "1m" else 2
        for i in range(len(ex) - step): out[ex[i] + 1] = ex[i + step]
        return out

    def iv(self, j, k, m, T, put):
        b = self.beta; x = self.rv20[k, j]; y = self.rv60[k, j]
        if not (x > 0 and y > 0): return None
        z = math.log(m) / math.sqrt(T); p = float(put)
        return self.scale * math.exp(b[0] + b[1] * math.log(x) + b[2] * math.log(y) + b[3] * math.log(self.vix[k] / 20) + b[4] * z + b[5] * z * z
                        + b[6] * math.log(T / .1) + b[7] * p + b[8] * p * z)

    def strike(self, j, k, S, T, target, put):
        r = self.rf[k]; lo, hi = (.35, 1.) if put else (1., 2.5)
        for _ in range(22):
            m = (lo + hi) / 2; iv = self.iv(j, k, m, T, put)
            if iv is None: return None, None
            d1 = (math.log(1 / m) + (r + .5 * iv * iv) * T) / (iv * math.sqrt(T)); dl = 1 - _N(d1) if put else _N(d1)
            if put: lo, hi = (m, hi) if dl < target else (lo, m)
            else: lo, hi = (m, hi) if dl > target else (lo, m)
        m = (lo + hi) / 2
        return m * S, self.iv(j, k, m, T, put)

@dataclass
class R:
    spec: Spec; eq: np.ndarray; trades: list; stats: dict

def run(M: Mkt, sp: Spec, start=date(2016, 1, 4), end=date(2026, 10, 30), mask=None, allow=None) -> R:
    M.scale = sp.iv_scale
    P = M.P; O, H, L, C = P.O, P.H, P.L, P.C; n = M.n; rng = random.Random(sp.seed)
    a = next(i for i, d in enumerate(M.days) if d >= start); z = max(i for i, d in enumerate(M.days) if d <= end)
    cash = sp.capital; pos: dict[int, dict] = {}; eq = np.full(n, np.nan); trades = []; cyc = M.cyc[sp.tenor]
    st = dict(puts=0, assigned=0, called=0, expired=0, profit=0, stopped=0, stock_exit=0, bankrupt=0, premium=0., opt_cost=0.)
    core_last = 0.
    def optcost(px, sh, q): return max(px * sp.spread, sp.tick) * sh + sp.comm * q
    def close_stock(j, p, px, k, why):
        nonlocal cash
        v = px * p["sh"]; c = v * sp.stock_bp / 1e4; cash += v - c
        trades.append((j, p["t0"], k, p["pnl"] + (px - p["basis"]) * p["sh"] - c, why)); del pos[j]
    for k in range(a, z + 1):
        tb = sp.idle_yield * M.rf[k - 1] * (M.days[k] - M.days[k - 1]).days / 365
        if sp.core:
            idle = max(cash - sum(p["K"] * p["sh"] for p in pos.values() if p["state"] == "put"), 0.)
            on = not sp.core_trend or M.spy[k - 2] > M.spy200[k - 2]
            want = idle if on else 0.
            cs = M.spy if sp.core == "SPY" else M.qqq
            g = cs[k] / cs[k - 1] - 1 if cs[k] > 0 and cs[k - 1] > 0 else 0.
            cash += want * g + (cash - want) * tb if cash > 0 else 0.
            cash -= abs(want - core_last) * 1e-4; core_last = want
        else:
            cash *= 1 + (tb if cash > 0 else 0)
        for j in list(pos):                                       # failures and delistings
            p = pos[j]; fz = P.fail.get(j)
            if fz is not None and k > fz:
                st["bankrupt"] += 1
                if p["state"] == "put":
                    cash -= p["K"] * p["sh"]; trades.append((j, p["t0"], k, p["pnl"] - p["K"] * p["sh"], "bankrupt"))
                else:
                    if p.get("opt"): pass
                    trades.append((j, p["t0"], k, p["pnl"] - p["basis"] * p["sh"], "bankrupt"))
                del pos[j]; continue
            if k > M.lastdata[j]:
                px = float(C[M.lastdata[j], j])
                if p["state"] == "put":
                    cash -= max(p["K"] - px, 0) * p["sh"]; trades.append((j, p["t0"], k, p["pnl"] - max(p["K"] - px, 0) * p["sh"], "delisted")); del pos[j]
                else:
                    if p.get("opt"): cash -= max(px - p["opt"]["K"], 0) * p["sh"]; p["pnl"] -= max(px - p["opt"]["K"], 0) * p["sh"]
                    close_stock(j, p, px, k, "delisted")
        for j in list(pos):                                       # stock exits decided at yesterday's close
            p = pos[j]
            if p["state"] == "stock" and p.get("sell") and not np.isnan(O[k, j]):
                if p.get("opt"):
                    o = p["opt"]; T = max((o["x"] - k) / 252, 1 / 252); iv = M.iv(j, k - 1, o["K"] / float(C[k - 1, j]), T, False) or .5
                    px = bs(float(O[k, j]), o["K"], T, M.rf[k], iv, False); c = px * p["sh"] + optcost(px, p["sh"], p["q"]); cash -= c; p["pnl"] -= c
                    p["opt"] = None
                st["stock_exit"] += 1; close_stock(j, p, float(O[k, j]), k, "stock exit")
        if k in cyc:
            x = cyc[k]; T = max((M.days[x] - M.days[k]).days, 1) / 365; q0 = k - 1
            for j, p in list(pos.items()):                        # covered calls
                if p["state"] != "stock" or p.get("opt") or np.isnan(O[k, j]) or np.isnan(C[q0, j]): continue
                S = float(O[k, j]); Kc, iv = M.strike(j, q0, S, T, sp.call_delta, False)
                if Kc is None: continue
                if sp.call_at_basis and Kc < p["basis"]:
                    Kc = p["basis"]; iv = M.iv(j, q0, Kc / S, T, False)
                px = bs(S, Kc, T, M.rf[k], iv, False); net = px * p["sh"] - optcost(px, p["sh"], p["q"])
                if net <= 0: continue
                cash += net; p["pnl"] += net; st["premium"] += net; p["opt"] = dict(K=Kc, x=x, prem=px)
            ok_mkt = M.vix[q0] >= sp.vix_lo and M.vix[q0] <= sp.vix_hi and (not sp.spy_up or M.spy[q0] > M.spy200[q0]) and (mask is None or mask[q0])
            free = sp.n_pos - len(pos)
            if ok_mkt and free > 0:
                mo = M.mo[q0]; prior = M.months[M.months.index(mo) - 1] if mo != M.months[0] else mo
                cand = []
                for j in P.rank.get(prior, [])[:sp.top_n]:
                    if j in pos or np.isnan(O[k, j]) or np.isnan(C[q0, j]) or not C[q0, j] > 0: continue
                    if allow is not None and j not in allow.get(M.days[k].year, ()): continue
                    if sp.trend and not C[q0, j] > M.s200[q0, j]: continue
                    if P.fail.get(j, 10 ** 9) <= q0: continue
                    if sp.off_high is not None and not C[q0, j] >= (1 - sp.off_high) * M.hi[q0, j]: continue
                    atm = M.iv(j, q0, 1., T, True)
                    if atm is None or not sp.iv_lo <= atm <= sp.iv_hi: continue
                    cand.append((atm, j))
                if sp.rank == "iv": cand.sort(reverse=True)
                elif sp.rank == "iv_low": cand.sort()
                elif sp.rank == "rand": rng.shuffle(cand)
                equity = cash + sum(float(C[q0, j]) * p["sh"] if p["state"] == "stock" else 0 for j, p in pos.items())
                for atm, j in cand:
                    if free <= 0: break
                    S = float(O[k, j]); rawp = P.raw.get(P.names[j], {}).get(prior); ref = float(C[M.mo_last[prior], j]) if prior in M.mo_last else np.nan
                    if not rawp or not ref > 0: continue
                    f = rawp / ref; K, iv = M.strike(j, q0, S, T, sp.delta, True)
                    if K is None: continue
                    shs = 100 * f; q = math.floor(min(sp.weight * equity, cash) / (K * shs))
                    if q < 1: continue
                    px = bs(S, K, T, M.rf[k], iv, True); sh = q * shs; net = px * sh - optcost(px, sh, q)
                    if net <= 0: continue
                    cash += net; st["puts"] += 1; st["premium"] += net
                    used = sum(p["K"] * p["sh"] for p in pos.values() if p["state"] == "put")
                    if used + K * sh > cash + 1e-6: cash -= net; st["puts"] -= 1; st["premium"] -= net; continue
                    pos[j] = dict(state="put", q=q, sh=sh, K=K, x=x, prem=px, t0=k, pnl=net, opt=None); free -= 1
        for j in list(pos):                                       # the day's options
            p = pos[j]; c_ = C[k, j]
            if np.isnan(c_): continue
            S = float(c_)
            if p["state"] == "put":
                if k >= p["x"]:
                    if S < p["K"]:
                        st["assigned"] += 1; cash -= p["K"] * p["sh"]; p.update(state="stock", basis=p["K"], opt=None); st_k = p["K"]
                    else:
                        st["expired"] += 1; trades.append((j, p["t0"], k, p["pnl"], "expired")); cash += 0; del pos[j]
                    continue
                if sp.profit or sp.stop:
                    T = max((M.days[p["x"]] - M.days[k]).days, 1) / 365; iv = M.iv(j, k, p["K"] / S, T, True) if p["K"] / S > .2 else None
                    if iv:
                        v = bs(S, p["K"], T, M.rf[k], iv, True)
                        hit = "profit" if sp.profit and v <= (1 - sp.profit) * p["prem"] else "stopped" if sp.stop and v >= sp.stop * p["prem"] else None
                        if hit:
                            c = v * p["sh"] + optcost(v, p["sh"], p["q"]); cash -= c; st[hit] += 1
                            trades.append((j, p["t0"], k, p["pnl"] - c, hit)); del pos[j]; continue
            else:
                o = p.get("opt")
                if o and k >= o["x"]:
                    if S > o["K"]:
                        st["called"] += 1; cash += o["K"] * p["sh"]; trades.append((j, p["t0"], k, p["pnl"] + (o["K"] - p["basis"]) * p["sh"], "called")); del pos[j]; continue
                    p["opt"] = None
                if sp.exit_below_200 and not np.isnan(M.s200[k, j]) and S < M.s200[k, j]: p["sell"] = True
                if sp.exit_loss and S < p["basis"] * (1 - sp.exit_loss): p["sell"] = True
        v = cash
        for j, p in pos.items():                                  # mark to market
            x = C[k, j]; S = float(x) if not np.isnan(x) else float(C[M.lastdata[j], j])
            if p["state"] == "put":
                T = max((M.days[p["x"]] - M.days[k]).days, 0) / 365; iv = M.iv(j, min(k, M.lastdata[j]), max(p["K"] / S, .05), max(T, 1 / 365), True) or .5
                v -= bs(S, p["K"], T, M.rf[k], iv, True) * p["sh"]
            else:
                v += S * p["sh"]
                if p.get("opt"):
                    o = p["opt"]; T = max((M.days[o["x"]] - M.days[k]).days, 0) / 365; iv = M.iv(j, min(k, M.lastdata[j]), max(o["K"] / S, .05), max(T, 1 / 365), False) or .5
                    v -= bs(S, o["K"], T, M.rf[k], iv, False) * p["sh"]
        eq[k] = v
    return R(sp, eq, trades, st)

def perf(M, eq, y0=None, y1=None):
    I = [i for i, d in enumerate(M.days) if not np.isnan(eq[i]) and (y0 is None or d.year >= y0) and (y1 is None or d.year <= y1)]
    e = eq[I]; r = e[1:] / e[:-1] - 1; f = np.array([M.rf[i] / 252 for i in I[:-1]]); yrs = (M.days[I[-1]] - M.days[I[0]]).days / 365.25
    pk = np.maximum.accumulate(e); sd = r.std()
    return dict(cagr=(e[-1] / e[0]) ** (1 / yrs) - 1 if e[-1] > 0 else -1., dd=float((e / pk - 1).min()), sharpe=float((r - f).mean() / sd * 252 ** .5) if sd else 0., vol=float(sd * 252 ** .5))
