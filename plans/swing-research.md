# Swing Futures Research (2026-11-22)

## Verdict
**I did not find a genuine swing edge, so I do not recommend building a swing bot from this research.** About 415 strategy variants were screened. Three candidates reached a final test and all three were rejected.

## How it was tested
- **Data:** roll-adjusted daily futures for 36 CME-group markets, through March 2024, from the public pysystemtrade dataset. CFTC positioning reports, Federal Reserve meeting dates, and Yahoo ETF and index data filled the other tests.
- **Windows, set before any result:** develop through 2012, validate 2013-2018, holdout 2019 to March 2024. April 2024 to November 2026 was a forward check using ETF proxies, because the futures dataset ends in March 2024.
- **Execution:** signals use the close, and trades fill one full day later, except the overnight test, which assumes close and open fills.
- **Costs:** a full bid-ask spread per side plus commission, with 2x cost stress on finalists.
- **Bar:** a candidate had to add to buy-and-hold, not merely make money.

## What happened
| Idea | Variants | Result |
|---|---:|---|
| Trend + carry blend | 15 | Sharpe 1.12 through 2012, then 0.24 in 2013-18. Rejected. |
| Broad screen: trend, carry, seasonality, dips, cross-market ranking | 75 | Two survivors. One depended on equities, the other mostly repeated Bumi. Rejected. |
| CFTC hedger and speculator positioning | 72 | None passed. |
| Pairs, spreads, month-end rebalancing | 162 | None passed. |
| **Trend sleeve on top of S&P** | finalist | **Passed 2019-24, failed 2024-26.** Rejected. |
| VIX futures premium | 7 | Filters were unstable between windows. Rejected. |
| Overnight / Asia-session drift | 13 | Gold, oil, bonds and FX failed. **Nasdaq reached the final test and failed.** |
| Fed-meeting drift and macro regimes | 72 | One survivor, which still trailed S&P in 2013-18. Rejected. |

## The closest candidate: S&P + diversified trend sleeve
| Period | Trend sleeve | S&P + 0.5 trend | S&P alone |
|---|---|---|---|
| 2019 to Mar 2024 (futures) | 7.1%/yr, Sharpe 0.64 | 18.5%/yr, Sharpe 0.97, -30.8% | 14.2%/yr, Sharpe 0.79, -34.8% |
| Apr 2024 to Nov 2026 (ETF proxy, over T-bills) | -1.5%/yr, Sharpe -0.11 | 7.0%/yr, Sharpe 0.47, -21.7% | 7.8%/yr, Sharpe 0.54, -19.2% |

Trend made 23.2% in 2022 while the S&P fell 19.6%, so it can help in a long bear market. It lagged in the rallies around it, and it did not earn its place in the most recent period.

## Limits of this research
- Only daily bars were tested. Hourly swing setups, price-action entries and true Asia-session futures entries were not.
- The 2024-26 check uses ETFs as stand-ins for futures, so it is approximate.
- FRED macro data could not be downloaded, so credit-spread signals were not tested.
- The holdout was used for two candidates, so it is no longer fully clean for new ideas.

## Recommended next step
Keep Bumi as the main system. If you want to continue, buy real hourly or minute futures data (Databento offers usage-based pricing and starter credits) and test one specific idea at a time, on data that has not been used here.

Code and the frozen pass/fail rules are in `app/research/swing/`, especially `FROZEN.md`. This is strategy research, not personal financial advice.
