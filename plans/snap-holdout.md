# Snap: the frozen holdout test

Written 2026-11-20 **before** looking at any pre-2016 data. All rules were developed on 2016–2026. The test period is the start of each ETF's Yahoo history (QQQ 1999, IWM 2000, DIA 1998, SPY 1993) through 2015, which includes the dot-com crash and 2008.

## Frozen candidates (no changes after seeing the results)
| | Entry | Stop | Exit |
|---|---|---|---|
| **A. Snap unchanged** | Snap | 3×ATR | first close above the 5-day average, 20-day limit |
| **B. Snap + trail** | Snap | 3×ATR | 1×ATR trailing stop only |
| **C. Snap + tighter trail** | Snap | 2×ATR | 1×ATR trailing stop only |
| **D. Breadth + delayed trail** | Snap, only when 3+ of the 4 ETFs signal | 2×ATR | 1×ATR trail that starts after +1R |

## Pass bar for 2000–2015 (fixed now)
Same costs and 1% risk, on a $50k fixed account, with at most 2× notional:
1. Profitable, with a Sharpe of at least 0.5
2. Beats at least 95% of 2,000 random-timing calendars
3. Worst true drawdown under $10k (20%)
4. At least 10 of the 16 years positive
