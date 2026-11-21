"""Bumi's reference backtest (research data, modeled 2x funds): `python -m app.backtest.bumi`. Saves and posts nothing."""

from __future__ import annotations

from app.research.experiments.longmkt import L2, build
from app.research.portfolio import run as portfolio_run
from app.settings import _read_json
from app import paths
from app.strategies import bumi


def run(core: bool = True):
    s = _read_json(paths.STRATEGY_CONFIG_DIR / "bumi.json")
    if not core:
        s = {**s, "core": {**s["core"], "weight": 0.0}}
    s = {**s, "universe": dict(L2)}          # the research market names its modeled 2x funds Q2, S2, I2, D2
    m = build(fee=0.0165)
    on = {u: bumi.track(m.bars[u], m.vix, s).want for u in s["universe"]}
    flags = bumi.calm(m.bars[s["core"]["trend_symbol"]], m.vix, s)
    return m, portfolio_run("Bumi", m, lambda k, h: bumi.weights({u: on[u][k] for u in on}, flags[k], s), idle="CASH")


if __name__ == "__main__":
    for core, name, want in ((True, "Bumi", 1_428_451), (False, "Defensive only", 1_111_169)):
        m, r = run(core)
        a = next(i for i, d in enumerate(m.dates) if d.year == 2001) - 1
        got = 50_000 * r.equity[-1] / r.equity[a]
        print(f"{name}: ${got:,.0f} vs run #77 ${want:,} ({'MATCH' if round(got) == want else 'DIFFERENT'})")
