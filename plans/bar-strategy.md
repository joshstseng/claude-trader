# Break and Retest ("bar"), run by Brix

Your strategy (2026-11-20), from studying RP Profits, run by **Brix** in Discord (strategy id `bar`; renamed from Mr. S / `mrs8` on 2026-11-20). It replaced the scratched mean-reversion strategy ([mrs-strategy.md](mrs-strategy.md), scratched after 6 years of tests showed no edge). Code: `app/strategies/bar.py`, settings `config/strategies/bar.json`, backtests `python -m app backtest --strategy bar …` (Uri posts them to `#backtests` until Brix has his own Discord bot).

## The baseline (run #35, set 2026-11-20)
The config defaults. Every new run is compared against it. All times Pacific.

| | Rule |
|---|---|
| Market | NQ, traded as MNQ ($2 a point). Backtested on HistData's Nasdaq-100 1m bars (a stand-in for NQ), Jan 2021 – Oct 2026 |
| Reference | The **5:00–5:15 AM 15m candle** (8:00 ET): its high, low and midpoint |
| Trend | **1h bias** at the breakout: the most recent 1h FVG price came back into and respected (no 1h close through it); else the last 1h break of structure. Only breakouts in the bias direction; no bias, no trade |
| Breakout | From the **6:05 AM** 5m bar on, the first 5m candle **closing beyond** the reference high (long) or low (short). First breakout only; one trade a day; no re-entry; never chase |
| Entry | **Limit at the midpoint**, in the breakout's direction (fills only if price trades through by a tick); cancelled if unfilled by **8:00 AM** |
| Stop (long; short mirrored) | 1) the **most recent 1h swing low** below the reference candle that still holds, if within **3× the 15m ATR**; 2) nearest holding **15m order block**; 3) **15m FVG**; 4) **5m FVG**; 5) **5m order block**; 6) worst case the **8:00 candle's low**. 2 ticks beyond; at least 5 points |
| Target | Flat **2R** |
| Break-even | At **+1R** the stop moves to entry |
| Exit | Stop / break-even / target minute by minute (a minute touching stop and target counts as the stop); flat at **9:00 AM** |
| Size, costs | 1% of $50,000 ($500) a trade, whole MNQ, at most 20; $0.75 per contract per side, 1 tick slippage on stop, break-even and 9:00 exits (none on the limit entry or target) |

Definitions: swing = a high/low with 2 bars on each side; order block = the last opposite-colour candle before a candle closing beyond it; FVG = a 3-candle gap. Each counts only once confirmed (no look-ahead).

**Baseline result:** 500 trades, 26% win, **−0.01R a trade after costs** (+0.03R before), −$1,140, worst drawdown −$17,002. By year: 2021 −0.13 · 2022 +0.12 · 2023 +0.14 · 2024 −0.18 · 2025 −0.12 · 2026 +0.22. Break-even, not an edge yet; the years swing.

## How we got here (6 years each, NY AM)
| Run | Change | After costs |
|---|---|---|
| #29 | First rules, no trend filter (6:00 start, 15m swing stop, target 5m lower high or 2R) | −0.04R (1,032 trades) |
| #30 | + 1h trend filter | −0.02R (497) |
| #31 | v2: 6:05 start, 1h swing stop, target 1h swing / unfilled 1h FVG within 2–4R | −0.06R |
| #32 | v2 with a flat 2R target | −0.06R |
| #33 | + the 1h low allowed up to 3× ATR | −0.06R |
| **#34 = #35** | **+ break-even at 1R** | **−0.01R** |

Notes: the 1h targets did worse than a flat 2R (unfilled 1h FVG targets won only 19%). Break-even was the one clear improvement (+0.05R a trade). Longs have been the stronger side in every version.

## Ideas not yet tested
- Longs only
- The 1h low allowed up to 4× ATR (the 15m order block is still the stop on ~217 of 500 trades)
- What separates the good years from the bad (volatility, the 8:00 candle's size) → when to sit out
- Real NQ futures data (Databento) to confirm on the actual contract
