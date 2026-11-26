# Nasdaq Intraday Breakout Research (2026-11-22)

## Current status (2026-11-22)
This rule is now the **Swing v1** baseline. **Swing v1.1** adds a 15-minute FVG exit and runs as a separate QQQ paper bot beside Bumi, with v1 tracked as a model. See `plans/swing-setup.md` and `app/research/swing/FROZEN_PD.md`.

## Verdict
**This is the first candidate with credible evidence of an edge, but it is not proven on real futures fills.** It passed every rule frozen in advance on 2023 to October 2026. Expect roughly **4-5% a year on a $100k-$250k MNQ account**, not the 9.6% from the QQQ test. It is an intraday strategy rather than a swing strategy, and it worked only on the Nasdaq.

## The strategy
- **Market:** MNQ (Micro Nasdaq-100), regular US session only, flat by the close.
- **Noise band:** for each time of day, average how far price moved from the open over the prior 14 sessions. Add that distance above the higher of today's open and yesterday's close, and subtract it below the lower of those two.
- **Entry:** every 30 minutes, go long if a completed 5-minute bar closes above the band, or short if it closes below. Fill at the next bar's open.
- **Exit:** leave when a 30-minute check is back inside the band, flip if it is beyond the opposite band, and always exit at the close.
- **Size:** target 1% daily volatility, capped at 2x account value, rounded down to whole contracts.

The likely reason it works is that large moves away from the day's normal range tend to continue during the session. A published "noise area" intraday momentum strategy uses the same general idea.

## How it was tested
- **Windows frozen first:** chosen on 2016-2019, validated on 2020-2022, final one-shot test on 2023 to October 2026.
- **Selection:** 343 variants across 7 markets were screened on 2016-2019 only. I froze the standard 14-day setting rather than the best-scoring neighbor.
- **Audit:** an independent rewrite matched every trading day in 2016-2022. A second Nasdaq-100 price source matched 2020-2022 closely.
- **Costs:** 0.6 bp per side in the ETF test. The MNQ test uses one tick plus $0.75 per contract per side.

## Results
| Test | Period | Return/yr | Sharpe | Max drop |
|---|---|---:|---:|---:|
| QQQ, chosen settings | 2016-2019 | 7.7% | 1.03 | n/a |
| QQQ, validation | 2020-2022 | 7.6% | 1.17 | -5.5% |
| QQQ, final test | 2023-Oct 2026 | 9.6% | 1.41 | -7.6% |
| QQQ, matching days only | 2023-Oct 2026 | 7.7% | 1.11 | -8.0% |
| Nasdaq-100 index prices, matching days | 2023-Oct 2026 | 4.5% | 0.67 | -9.7% |
| **MNQ whole contracts, $100k** | 2023-Oct 2026 matching days | **4.2%** | **0.80** | **-7.1%** |
| **MNQ whole contracts, $250k** | 2023-Oct 2026 matching days | **5.2%** | **0.84** | **-8.0%** |

The strategy's daily correlation with SPY and QQQ was about zero in the final test. It made money in 2022 while QQQ fell. It trails QQQ on raw return (QQQ made about 27.6% a year in 2023-2026), so its value is as a separate return stream rather than a replacement for holding the market.

## Risks
1. **Nasdaq only.** The same rule failed on Russell, gold, silver, oil, bonds, and the forex ETFs with enough data. On SPY it was inconsistent.
2. **Execution cost.** On QQQ, the 2023-2026 edge is close to zero at 3 bp per side.
3. **A few big days.** The top 10 days were 65% of final-test profit. Without them it made 3.4% a year. Expect long flat stretches.
4. **Account size.** At $50k, whole-contract rounding skipped about half the days and made only 1.8% a year in 2023-2026, including a $1,517 loss in 2026.
5. **Data.** No real MNQ fills were tested. The index source is also missing 111 trading days in 2023.

## Forex and oil
- **Oil:** tested through USO and failed (final-test Sharpe -2.05).
- **Forex:** FXE and FXY failed, but their data is thin. FXB and FXA had too little data to test. Dukascopy's free feed was too throttled, and HistData has an expired security certificate, so **forex has not had a fair test.**

## Recommended next step
Run a read-only shadow test on live MNQ prices for 2-3 months, with no orders, and compare its signals and estimated fills with this backtest. Only then consider paper trading through a futures broker.

Code and frozen rules are in `app/research/swing/`, especially `FROZEN_INTRADAY.md`. This is strategy research, not personal financial advice.
