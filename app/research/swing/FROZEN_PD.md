# Swing v1 early exits from PD arrays, frozen before any result (2026-11-22)

Swing v1 stays unchanged as the baseline. Entries, sizing, 30-minute exits, flips and the 4:00 PM flat rule stay the same. This test only adds an earlier exit.

## Early exit
For a long, exit at the next 5-minute open after a confirmation candle closes below the protecting bullish array. Shorts are mirrored.
- Fair value gap (FVG): three-candle gap. It is disrespected on a close through the far side of the gap.
- Order block: last opposite-color candle before a candle closes beyond its high (long) or low (short). It is disrespected on a close through the far side of that candle.
- Swing structure: latest confirmed three-candle swing low (long) or high (short). It is disrespected on a close through it.

Arrays are built from completed 5m, 15m, 30m or 1h candles, including prior sessions. Confirmation uses a completed 5m or 15m candle, never a lower timeframe than needed and never a partial candle.
- Fixed: use the latest valid array known at entry.
- Trailing: move to the newest valid array as the trade develops.
- After an early exit: either re-enter at a later 30-minute check if price is still beyond the band, or block that direction until a check returns inside the band.

## Selection
- Choose on 2016-2019 only. A variant advances if its Sharpe beats v1, it is profitable at 2x costs, and it has 100+ trades.
- At most one finalist per array type: the highest 2016-2019 Sharpe.
- 2020-2022 gate: Sharpe must beat v1.
- 2023 to October 2026, run once: Sharpe and annual return must both beat v1, and it must stay profitable at 2x costs.

These years were already seen while developing v1, so even a pass is weaker evidence and must also prove itself in the live shadow test.

## Result
84 variants. Finalists: swing structure and order block failed 2020-22. **15-minute FVG, 15-minute confirmation, latest array, block same-side re-entry passed all gates.**

| QQQ | v1 | FVG exit |
|---|---|---|
| 2016-19 | 7.7%/yr, Sharpe 1.03, -10.0% | 8.6%, 1.30, -4.8% |
| 2020-22 | 7.6%, 1.17, -5.5% | 7.6%, 1.28, -4.2% |
| 2023-Oct 2026 | 9.6%, 1.41, -7.9% | 11.4%, 1.73, -6.1% |

Audit (x81_pd_audit.py): a separate candle-by-candle rewrite matched. Whole MNQ at $100k, 2023-26: 6.7%/yr, Sharpe 1.31, -5.2% vs v1 4.2%, 0.80, -7.1%. No random-exit run out of 200 beat it, though the best came close.
Limits: the re-entry block matters, since 15m trail with re-entry had Sharpe 1.28 vs v1 1.30. Of 16 nearby settings, 10 beat v1, 3 tied and 3 trailed. Most of the return gain came from 2024 and 2026; 2021, 2023 and 2025 were slightly worse than v1.
