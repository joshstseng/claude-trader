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

## Result (run once, 2026-11-20): all four FAILED the bar
Period: May 2000 to December 2015, the first dates all four ETFs have data. Trading starts in 2001, after the 200-day average has warmed up.

| | Trades | PF | Profit | Sharpe | Beats random | True drawdown | Years positive | Bar |
|---|---|---|---|---|---|---|---|---|
| A. Snap unchanged | 909 | 1.28 | +$17.0k | 0.38 | 91.6% | −$6.0k | 10/16 | fail |
| B. Snap + trail | 1,054 | 1.23 | +$16.9k | 0.41 | 98.2% | −$8.3k | 9/16 | fail |
| C. 2×ATR stop + trail | 1,058 | 1.25 | +$27.4k | 0.44 | 98.8% | −$12.2k | 10/16 | fail |
| D. Breadth + delayed trail | 478 | 1.40 | +$41.5k | just under 0.50 | 100% | −$10.9k | 9/16 | fail |

For context, buy and hold over the same period: QQQ 3.0% a year (worst drop −80%), SPY 4.5% a year (−55%).

**What this means:**
- All four made money through the dot-com crash and 2008, and B, C and D beat random timing. So the dip effect is real, but weaker than 2016–2026 suggested.
- The 2016–2026 headline numbers (+$57k, 28.7% a year) should not be expected going forward.
- This holdout has now been used. Anything designed after seeing it can't be judged on it as untouched data.

# Second holdout, frozen 2026-11-20 before running
Developed on QQQ, SPY, IWM and DIA, 2001–2026. The test is **15 ETFs never used before 2016** (XLK, XLF, XLV, XLY, XLP, XLI, XLU, XLB, XLE, MDY, EFA, EWJ, EWG, EWU, EWC), from August 2001 (EFA's start) to December 2015. Each ETF is traded on its own at 1% risk and the results are pooled.

| | Entry | Stop | Exit |
|---|---|---|---|
| **A. Snap (control)** | above the 200-day; RSI(2) < 10 or IBS < 0.1 | 3×ATR | first close above the 5-day average |
| **E. Fear dips** | **VIX above 15**, no 200-day filter; RSI(2) < 10 or IBS < 0.1 | 3×ATR | first close above the 5-day average |
| **F. Fear + trend + trail** | **VIX above 20**, above the 200-day; RSI(2) < 10 or IBS < 0.1 | 3×ATR | 1.5×ATR trailing stop |

**A candidate passes if all hold:**
1. Pooled profit factor of at least 1.3
2. At least 11 of the 15 ETFs are profitable
3. Beats at least 95% of 1,000 random-timing calendars (pooled)
4. Higher pooled profit factor than the control (A)

## Second holdout result (run once, 2026-11-20): E and F PASSED
| | Trades | Pooled PF | Profit (ETFs traded separately) | ETFs profitable | Random median | Beats random | Bar |
|---|---|---|---|---|---|---|---|
| A. Snap (control) | 3,301 | 1.38 | +$80.2k | 15/15 | +$43.8k | 99.9% | passes the first three checks |
| **E. Fear dips** | 3,995 | 1.40 | +$112.1k | 15/15 | +$58.4k | 99.5% | **pass** |
| **F. VIX > 20 + trend + 1.5×ATR trail** | 941 | **2.02** | +$81.2k | 15/15 | +$23.1k | **100%** | **pass** |

**Caveats:** these ETFs are correlated, so 15 profitable ETFs are not 15 independent proofs. The dollar totals are per-ETF sums with no portfolio cap, so they are not what one account would earn.
