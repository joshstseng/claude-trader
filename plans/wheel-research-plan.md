# Wheel research: plan frozen before any backtest

Written 2026-11-21, before looking at any wheel result. Research only. No orders, no deployment, no change to Uri, Orbi or Bumi.

## Questions
1. Does selling puts or the wheel beat buy-and-hold, after costs?
2. In which markets is it strong, and in which is it poor (calm, fearful, downtrend, by VIX)?
3. Does sitting out in specific markets improve it, without hindsight?
4. Do high-IV stocks pay enough to cover their losses, or is the premium a trap?
5. Which rules matter: delta, days to expiry, profit-taking, stop, trend filter, position limits?
6. Which stocks are reasonable candidates for 2027?

## Evidence, strongest first
| Layer | Data | Why |
|---|---|---|
| **A. Real index strategies** | Cboe PUT, WPUT, BXM, BXMD, PPUT, CNDR, 1986 to 2026 | Published, real option prices, decades of crashes |
| **B. Real stock options** | Alpaca option bars, February 2024 to 2026 | Real traded prices, but a short, mostly rising period |
| **C. Modeled stock wheel** | Alpaca stock bars 2016 to 2026, **including delisted and bankrupt stocks**, with option prices modeled and calibrated to B | Long enough to include 2018, 2020 and 2022 without survivorship bias |

## Split
- **Develop rules on 2016 to 2021.**
- **One look at 2022 to October 2026**, after the candidates are frozen.

## Pass bar for a stock wheel (fixed now)
Over both the full period and the 2022 to 2026 holdout, after costs:
1. Annual return above buy-and-hold SPY
2. Sharpe above SPY
3. Worst drop smaller than SPY's
4. Positive in most calendar years
5. Beats at least 95% of random-timing runs
6. Still beats SPY's return with option costs doubled

Beating QQQ is reported, but is not required to pass.

## Honesty rules
- Stocks are chosen each month using only data known then, from a universe that includes stocks that later failed.
- A stock that went bankrupt counts as a loss to zero, not its last traded price.
- Option sales fill below the mid price. Contracts are whole, 100 shares each.
- Layer C is a model. It is only trusted as far as it matches the real prices in layer B.

## Frozen candidates for the one 2022 to 2026 look
Chosen on 2016 to 2021 only, written before running the holdout. Each is measured as the median of 40 random 8-stock portfolios from the 100 or 200 most liquid stocks, $100k, 25-delta monthly puts, 5% option spread.

| | Rules |
|---|---|
| **W1 Classic wheel** | Sell puts every month, then 30-delta calls after assignment. T-bills on idle cash |
| **W2 Fear wheel** | New puts only when VIX is at least 20. 15-delta calls after assignment. T-bills on idle cash |
| **W3 QQQ trend + Fear wheel** | W2, with idle cash in QQQ while SPY is above its 200-day, otherwise T-bills |
| **W4 SPY trend + Fear wheel** | W3, with SPY as the core |
| **Control: QQQ trend, no options** | W3 without any option trades. If W3 does not beat this, the options add nothing |
| **Control: SPY trend, no options** | W4 without any option trades |

## Holdout result (run once, 2026-11-22): every wheel candidate FAILED
Median of 40 random 8-stock portfolios, after costs.

| | 2016-2026 | Worst drop | Sharpe | 2022-2026 | Beats random VIX timing |
|---|---|---|---|---|---|
| SPY | 14.8% | -34% | 0.74 | 11.4% | |
| QQQ | 19.4% | -35% | 0.81 | 12.6% | |
| W1 Classic wheel | 3.4% | -32% | 0.15 | 3.8% | |
| W2 Fear wheel | 5.6% | -23% | 0.39 | 3.6% | 59% |
| W3 QQQ trend + Fear wheel | 14.1% | -29% | 0.73 | 7.6% | 51% |
| W4 SPY trend + Fear wheel | 11.0% | -27% | 0.64 | 6.4% | 33% |
| Control: QQQ trend, no options | 14.6% | -28% | 0.78 | 7.6% | |
| Control: SPY trend, no options | 11.1% | -22% | 0.76 | 7.1% | |

The VIX filter looked strong in development and showed no edge over random timing. Adding the fear wheel to a trend core added nothing. Anything found after this point is exploratory.

## Watchlist rule, frozen before its walk-forward test
Each year, using only data through the end of the prior November, take the 12 most liquid stocks that pass all of these:
1. Top 100 by dollar volume
2. 60-day realized volatility between 20% and 60%
3. Within 25% of the 1-year high
4. No single-day drop worse than 20% in the past year
5. Above the 200-day average

The bot wheels those 12 for the next calendar year: 25-delta monthly puts, 20-delta calls not below the assignment price, up to 8 positions.
