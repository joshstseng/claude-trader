# Snap research: what survived

Written 2026-11-20 after an evening of testing. **Snap itself is unchanged and nothing live was touched.** Detailed logs: [snap-holdout.md](snap-holdout.md), [snap-crazy.md](snap-crazy.md), [snap-scenarios.md](snap-scenarios.md). Scripts: [app/research/experiments/](../app/research/experiments/).

## The system that survived: "Defensive"
| | |
|---|---|
| **Watch** | QQQ, SPY, IWM, DIA, after each close |
| **Buy** | VIX above 20, **and** the ETF above its 200-day average, **and** (2-day RSI under 10 **or** close in the bottom 10% of the day's range) |
| **Trade** | at the next open, 25% of the account in that index's 2× ETF (QLD, SSO, UWM, DDM) |
| **Exit** | a stop starting 3×ATR below entry, then trailing 1.5×ATR under the highest price |
| **Idle cash** | T-bills |

## Results
| Period | Defensive | Worst drop | Sharpe | S&P 500 | Nasdaq-100 |
|---|---|---|---|---|---|
| **1990–2000** (index data, 3 indexes, 5 bp) | **16.1%/yr** | −34% | 1.13 | 13.8%, −20% | 28.6%, −36% |
| **2001–2026** | **12.8%/yr** | **−23%** | **1.09** | 8.9%, −55% | 10.8%, −80% |

**2001–2026 detail:**
- 20 of 26 years positive; worst year −11% (2008, when the S&P fell 37%)
- Beat the S&P in 16 of 26 years, and in 78% of rolling 5-year windows
- Beat the Nasdaq in only 12 of 26 years, and in **36%** of rolling 5-year windows
- In the S&P's five down years: −1%, −1%, −11%, +9%, −4% against −12%, −22%, −37%, −5%, −18%
- Holds a dip position about 29% of days

**It is not a bull-market beater.** It wins by losing far less in crashes. In 2017 it made +1% while the S&P made +22%. Since 2016 it has roughly matched the S&P and trailed QQQ.

**Robustness (2001–2026):**

| Change | Return a year | Worst drop |
|---|---|---|
| VIX floor 15 / 18 / 22 / 25 | 12.7 / 12.4 / 9.0 / 6.1% | −25 / −25 / −23 / −21% |
| Trail 1 / 1.25 / 1.75 / 2×ATR | 10.8 / 12.0 / 11.7 / 12.4% | −18 / −21 / −24 / −25% |
| Starting stop 2 / 4×ATR | 12.5 / 12.9% | −23% |
| Position size 10 / 15 / 20 / 30% | 6.3 / 8.5 / 10.6 / 14.8% | −10 / −15 / −19 / −28% |
| Slippage 5 / 10 bp | 12.0 / 11.1% | −24% |

## What we learned
1. **The dip edge is real but smaller than 2016–2026 suggested.** It beat random timing on untouched data, including 15 other ETFs.
2. **Fear is what makes it work.** Dips with VIX under 15 have almost no edge (profit factor 1.05); with VIX over 20 it's 2.17.
3. **Holding longer mostly just captured the market's rise.** Random entries held 20 days made $37.7k of the real $44.5k.
4. **Re-optimizing hurt.** Picking the best of 360 variants each year made +$14.3k against +$26.5k for leaving Snap alone.
5. **Partials, tight stops and bigger R targets didn't add a robust edge.** Tight stops raised drawdowns; partials roughly matched not using them.
6. **The highest-return version failed.** Trend QQQ plus 25% adds made 18.6% a year but came close to a margin call (94% of equity). The 15% "Balanced" version failed the 1990s test with a −43% drop.

## Honest limits
- More than 500 variants were examined, so some selection bias remains even with holdouts.
- 2× ETF returns before 2006 are simulated, with a cost calibrated to the real funds since 2016.
- The 1990s test used index data with unreliable opens, so fills are effectively at the close.
- Taxes are ignored. Frequent short-term trades would matter in a taxable account.
- **Only forward paper trading can confirm it.**
