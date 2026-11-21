# Snap scenarios: can it beat just holding the market?

Written 2026-11-20 after the user asked for Snap to beat simply owning an ETF. **Snap itself is unchanged.** These are portfolio-level backtests (app/research/portfolio.py).

**How every scenario is simulated:**
- $50k start, compounding
- trades at the next open, 1 bp slippage each way
- 7% margin interest on borrowed money; idle cash in T-bills (BIL) where noted
- gross exposure capped at 2× (Alpaca's overnight margin)
- data January 2016 to October 2026, dividend-adjusted

**Read with care:** 2016–2026 was an exceptional decade for the Nasdaq, and every year has been looked at. Anything that uses leverage or the Nasdaq looks better in hindsight than it will in a typical decade. Paper trading is the real test.

## Results
| Scenario | Ends at | Return a year | Worst drop | Sharpe | 2016–20 | 2021–23 | 2024–26 |
|---|---|---|---|---|---|---|---|
| **Buy and hold SPY** | $221k | 14.7% | −34% | 0.88 | 15.2% | 9.9% | 19.1% |
| **Buy and hold QQQ** | $340k | 19.4% | −35% | 0.91 | 24.4% | 10.1% | 20.8% |
| Snap, 25% per position | $91k | 5.6% | −10% | 0.90 | 3.1% | 6.6% | 9.2% |
| Snap, 25% per position, idle cash in T-bills | $105k | 7.1% | −10% | **1.12** | 3.7% | 8.1% | 12.5% |
| Snap, 50% per position (up to 2×) | $148k | 10.5% | −22% | 0.85 | 5.3% | 12.7% | 18.0% |
| Snap in 2× ETFs, 25% per position | $150k | 10.7% | −21% | 0.87 | 5.6% | 12.8% | 17.8% |
| Snap in 2× ETFs, 50% per position | $362k | 20.1% | −43% | 0.84 | 9.1% | 25.2% | 36.1% |
| Trend: QQQ above its 200-day average, else T-bills | $237k | 15.5% | −23% | 0.96 | 15.7% | 13.3% | 17.3% |
| Trend: QLD (2×) when QQQ is above its 200-day average | $588k | 25.6% | −42% | 0.86 | 27.7% | 21.8% | 25.9% |
| Trend: TQQQ (3×) when QQQ is above its 200-day average | $1,140k | 33.5% | −58% | 0.84 | 37.5% | 28.6% | 31.9% |
| QQQ always, plus Snap adds 25% each (margin) | $512k | 24.0% | −37% | 0.97 | 26.4% | 15.4% | 29.3% |
| Trend QQQ, plus Snap adds 25% each | $359k | 20.0% | **−29%** | 0.98 | 17.5% | 19.0% | 25.6% |
| **Trend QQQ, plus Snap adds 25% each in 2× ETFs** | **$519k** | **24.1%** | −35% | **1.01** | 18.5% | 24.2% | 34.6% |

**Sharpe** is return per unit of ups and downs; higher is better.

**The 2× ETFs Snap's adds use:**

| Snap signal on | 2× ETF bought |
|---|---|
| QQQ | QLD |
| SPY | SSO |
| IWM | UWM |
| DIA | DDM |

## The best all-round candidate: "Trend QQQ, plus Snap adds in 2× ETFs"
**The rules:**
1. **Hold QQQ** with the whole account while QQQ closes above its 200-day average; otherwise hold T-bills.
2. **On each Snap signal** (any of QQQ, SPY, IWM or DIA), add 25% of the account in that index's 2× ETF.
3. **Exit each add** on Snap's normal exit: the first close above the 5-day average, or the stop.

**Stress tests, all still above buy-and-hold QQQ's 19.4% a year:**

| Change | Return a year | Worst drop |
|---|---|---|
| Add size 15% | 20.7% | −30% |
| Add size 35% | 27.2% | −38% |
| Trend filter 150-day / 250-day average | 26.3% / 23.7% | about −36% |
| Trend filter with a 2% band (fewer whipsaws) | 25.1% | −36% |
| 5 bp slippage | 22.3% | −35% |
| 10% margin interest | 23.6% | −35% |
| No T-bills on idle cash | 23.8% | −35% |
| Only QQQ's own Snap signals | 19.4% | **−25%** |

**Its weak spot:** in 2016–2020 it made about 18.5% a year against QQQ's 24.4%. The 200-day filter sells late and buys back late around fast V-shaped recoveries (2018, 2020). It pulls ahead in years with a real bear market (2022) and in strong bull years.

## Takeaways
- **Snap alone can't beat the market;** it's invested only about 18% of the time.
- **Two things help:**
  - **staying invested while the trend is up** (the 200-day trend core)
  - **using Snap to buy dips on top,** where the 2× ETFs make each dip count more
- **Pure leverage** (TQQQ on trend) makes the most money, but has the worst drops (−58%).

## Next (not done)
Choose one scenario to become a bot. It would run like Snap, deciding after the close and trading at the open, on Alpaca, and starting in shadow/paper mode.
