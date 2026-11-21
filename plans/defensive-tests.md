# Defensive: real-world tests

Started 2026-11-20. Research only. Nothing here changes Snap, Uri, Orbi or Brix.

## Fourth holdout, frozen before running
**Data:** the 15 ETFs from the second holdout (XLK, XLF, XLV, XLY, XLP, XLI, XLU, XLB, XLE, MDY, EFA, EWJ, EWG, EWU, EWC). Their 2016-01-01 to 2026-10-30 prices have never been used for these rules. 2015 is used only to warm up the averages.

**Not fully independent:** these are the same years as the US development data, and these ETFs move with the US market.

| | Entry | Stop | Exit |
|---|---|---|---|
| **A. Snap (control)** | above the 200-day; RSI(2) < 10 or IBS < 0.1 | 3×ATR | first close above the 5-day average |
| **F. Defensive signal** | VIX above 20, above the 200-day; RSI(2) < 10 or IBS < 0.1 | 3×ATR | 1.5×ATR trailing stop |

Each ETF is traded on its own at 1% risk, 1 bp slippage, and the results are pooled, exactly as in the second holdout.

**F passes only if all hold:**
1. Pooled profit factor of at least 1.3
2. At least 11 of the 15 ETFs are profitable
3. Beats at least 95% of 1,000 random-timing calendars (pooled)
4. Higher pooled profit factor than the control (A)

Run once. No rule changes after seeing the result.

## Results (2026-11-20)

### Fourth holdout: F PASSED (run once)
| | Trades | Pooled PF | Profit | ETFs profitable | Random median | Beats random | Bar |
|---|---|---|---|---|---|---|---|
| A. Snap (control) | 2,953 | 1.35 | +$70.9k | 13/15 | +$32.4k | 100% | passes the first three checks |
| **F. Defensive signal** | 918 | **1.40** | +$36.6k | **12/15** | +$24.1k | **98.0%** | **pass** |

F's profit factor beat the control only narrowly, and the control made more dollars. Per-ETF sums, not one account.

### Real 2× ETF prices, 2016 to October 2026 (1 bp)
| | Modeled 2× prices | Actual 2× prices |
|---|---|---|
| Defensive | 15.7%/yr, −15.1% | 15.8%/yr, −15.0% |
| Defensive + 50% QQQ | 17.4%/yr, −19.2% | 17.4%/yr, −19.2% |

The 2× model matches the real funds closely.

### Stop execution, actual 2× prices, 2016 to October 2026
| | Check the low after the close, sell next open | Resting intraday stop |
|---|---|---|
| Defensive | **15.8%/yr, −15.0%** | 11.4%/yr, −19.2% |
| Defensive + 50% QQQ | **17.4%/yr, −19.2%** | 13.0%/yr, −23.1% |

**The tested edge depends on this exit.** Do not replace it with a resting stop. Fills are estimated from daily bars; 5-minute data was not used. The 1990s can't judge this because its opens are unreliable.

### Exposure caps, 2001 to October 2026 (Defensive)
| | Return | Worst drop | Sharpe |
|---|---|---|---|
| No cap, 25% trades | 12.9% | −23.2% | 1.10 |
| 75% cap | 10.8% | −22.5% | 1.08 |
| 50% cap | 8.3% | −18.4% | 1.08 |
| 18.75% trades, no cap | 10.2% | −17.8% | 1.15 |
| 15% trades, no cap | 8.5% | −14.5% | 1.20 |

Caps rejected. Smaller trades reduce risk more efficiently.

### Cost note
Backtest #76 used a 0.95% 2× cost instead of the calibrated 1.65%. The effect is about 0.1 point a year on Defensive.
