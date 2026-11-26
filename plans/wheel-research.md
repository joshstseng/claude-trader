# The Wheel: full research report

Written 2026-11-22. Research only. **No orders were placed, nothing was deployed, and Uri, Orbi and Bumi were not changed.** This is strategy research, not personal financial advice.

## 1. Bottom line

**The wheel does not beat the market, so I would not build it as a market-beating bot.** It is a real, repeatable way to collect income and reduce risk, but in these tests that risk reduction was about what you would get from simply holding less stock.

| 2017 to October 2026 | Return per year | Worst drop | Volatility | Sharpe |
|---|---|---|---|---|
| **Best wheel (watchlist rule)** | **11.1%** | **-21%** | 12.3% | **0.71** |
| 70% SPY + 30% T-bills | 11.4% | -25% | 12.7% | 0.72 |
| SPY | 14.9% | -34% | 18.1% | 0.72 |
| QQQ | 20.3% | -35% | n/a | 0.82 |

The five findings that matter most:

1. **Every frozen wheel candidate failed its out-of-sample test.** None beat SPY from 2022 to 2026.
2. **Selling puts wins in flat and falling markets and loses in strong rallies.** Over 30 years of real Cboe data, the put-selling index beat the S&P in 39% of rolling 12-month periods.
3. **Higher IV did not reliably mean more profit.** The highest-volatility fifth of stocks had the largest losses in 2022 to 2026.
4. **Sitting out high-VIX markets makes the wheel worse.** Fear is when option sellers are paid best.
5. **The rules that helped were about not capping your upside:** far-out calls, and never selling a call below your cost.

## 2. What the wheel is

1. **Sell a cash-secured put** below the current price and keep the premium.
2. **If the stock stays above the strike,** the put expires. Repeat.
3. **If it falls below the strike,** you buy 100 shares at the strike.
4. **Sell covered calls** above your cost and keep that premium.
5. **If the shares are called away,** you are back in cash. Repeat.

**Why it feels great:** most trades win, and income arrives every month. In our best version, every *closed* trade was a winner. That number is misleading, because losing positions simply stay open as stock you are stuck holding.

**The real payoff:** you take nearly all of a stock's downside, while your upside is capped at the premium plus the distance to the call strike.

## 3. How this was tested

| Layer | Data | Size | Use |
|---|---|---|---|
| **A. Real index strategies** | Cboe PUT, WPUT, BXM, BXMD, CNDR, PPUT | August 1996 to 2026 | Decades of real option-selling returns |
| **B. Real stock options** | Alpaca expired contracts and traded prices | 1.29M price observations, 324 stocks, 2024 to 2026 | Real premiums and real put results |
| **C. Stock wheel simulator** | Alpaca daily bars | 1,628 stocks, 2016 to 2026, including 37 companies that failed | Full portfolio backtests |

**How I kept it honest:**
- I wrote the pass bar and candidates down before running the holdout ([wheel-research-plan.md](wheel-research-plan.md)).
- Rules were developed on 2016 to 2021, with one look at 2022 to 2026.
- Stocks were chosen each month using only information known then.
- Bankrupt companies count as a total loss.
- Trades use whole contracts and fill 5% worse than the modeled premium.
- Most results are the median of 40 random portfolios, so one lucky stock can't drive them.

**How well the option model matches reality:** fitted on 2024 and tested on 2025 to 2026, its typical implied-volatility error was 14%, with a median premium 3.4% below real prices. I then scaled it to match real premium dollars. Even an optimistic version with IV 5% above real did not change the verdict.

## 4. Thirty years of real option-selling results

August 1996 to October 2026:

| Strategy | Return per year | Worst drop | Sharpe |
|---|---|---|---|
| **S&P 500 total return** | **10.4%** | -55% | 0.49 |
| **Sell monthly S&P puts (PUT)** | 8.5% | **-37%** | **0.53** |
| Buy S&P, sell 30-delta calls (BXMD) | 9.4% | -47% | 0.50 |
| Buy S&P with protective puts (PPUT) | 7.2% | -42% | 0.41 |
| Iron condors (CNDR) | 3.5% | -20% | 0.19 |

Weekly put-selling (WPUT) made 4.8% a year from 2006, against 11.0% for the S&P.

**The gap has widened lately.** From 2016 to 2026, PUT made 8.4% a year and the S&P made 15.0%.

## 5. Where the wheel is strong and where it is poor

### By monthly market move (real data, 362 months)

| S&P month | Months | S&P | Put-selling | Put-selling beat S&P |
|---|---|---|---|---|
| **Crash, below -7%** | 21 | -9.36% | -6.93% | 71% |
| **Down 3 to 7%** | 38 | -4.71% | -2.02% | **95%** |
| **Down 0 to 3%** | 68 | -1.49% | -0.09% | **87%** |
| **Up 0 to 2%** | 83 | +1.03% | +1.19% | 47% |
| **Up 2 to 4%** | 70 | +2.95% | +1.59% | 7% |
| **Up 4 to 7%** | 56 | +5.30% | +2.90% | 4% |
| **Up more than 7%** | 26 | +8.63% | +4.70% | 4% |

### By 12-month market return

| S&P over 12 months | S&P | Put-selling | Put-selling won |
|---|---|---|---|
| Below -10% | -21.0% | -10.2% | **100%** |
| -10% to 0% | -5.1% | +1.9% | **84%** |
| 0% to 10% | +5.8% | +5.7% | 65% |
| 10% to 20% | +15.1% | +10.4% | 20% |
| 20% to 30% | +24.0% | +16.0% | 10% |
| Above 30% | +37.0% | +25.3% | 3% |

**The wheel is strongest in:** sideways markets, slow declines and bear markets.

**The wheel is weakest in:** strong bull markets and sharp V-shaped recoveries, because it holds too little upside. It still loses money in crashes.

### Crashes and the rebound after

| Episode | S&P | Put-selling | S&P next 12 months | Put-selling next 12 months |
|---|---|---|---|---|
| Dot-com | -47.4% | -22.3% | +36.2% | +32.5% |
| 2008 crisis | -55.3% | -34.8% | +72.3% | +52.6% |
| 2011 | -18.6% | -13.7% | +34.5% | +29.7% |
| 2015 to 2016 | -12.8% | -4.5% | +29.4% | +18.6% |
| Q4 2018 | -19.4% | -15.4% | +39.9% | +18.7% |
| COVID | -33.8% | -28.9% | +77.8% | +47.5% |
| 2022 | -24.5% | -13.7% | +23.0% | +18.1% |
| 2025 tariffs | -18.7% | -15.0% | +38.6% | +25.6% |

It cushions the fall, then misses much of the recovery.

## 6. Should the bot sit out certain markets?

**Mostly no.** Results for the real S&P put index, August 1996 to 2026, moving to T-bills under each rule:

| Rule | Return per year | Worst drop | Sharpe |
|---|---|---|---|
| **Always on** | **8.5%** | -37% | 0.52 |
| Sit out VIX above 25 | 4.0% | -26% | 0.26 |
| Sit out VIX above 30 | 5.8% | -25% | 0.43 |
| Sit out VIX above 40 | 7.6% | -31% | 0.54 |
| Sit out VIX above 50 | 8.5% | -33% | 0.58 |
| Sit out VIX below 15 | 6.7% | -37% | 0.40 |
| **Sit out when S&P is below its 200-day** | 6.4% | **-20%** | **0.59** |
| Only trade when VIX is at least 20 | 5.4% | -36% | 0.31 |

- **High VIX is usually the wrong time to leave.** The strongest rebounds and richest premiums happen then.
- **The 200-day filter is the only useful risk control here.** It cuts the worst drop almost in half, at a cost of about 2 points a year.
- **A VIX-only stock wheel looked excellent until the holdout.** In development it had a Sharpe of 1.00. Over the full period it beat only 59% of random-timing runs, so I treat that edge as luck.

## 7. Real option results by stock type

These are 4,360 real puts held to expiry, February 2024 to September 2026, about 25 delta and 47 days, with a 5% fill penalty. Returns are on the cash securing each put, before T-bill interest.

| Real IV | Trades | Win rate | Assigned | Put return per trade | Same stock |
|---|---|---|---|---|---|
| Under 30% | 1,369 | 86% | 18% | +0.42% | +1.40% |
| 30 to 45% | 1,522 | 82% | 23% | +0.39% | +1.71% |
| 45 to 60% | 662 | 83% | 22% | +1.12% | +4.53% |
| 60 to 80% | 404 | 81% | 26% | +1.44% | +6.37% |
| 80 to 120% | 339 | 77% | 31% | +1.77% | +5.90% |
| Above 120% | 64 | 64% | 45% | +1.43% | -11.39% |
| **All** | **4,360** | **83%** | **22%** | **+0.73%** | **+2.61%** |

- **Higher IV earned more in this window, but 2024 to 2026 favored volatile stocks.** Above 120% IV, nearly half the puts were assigned.
- **The longer test disagrees.** Over 2022 to 2026, the highest-IV fifth of stocks averaged -0.23% per put, with a worst-5% outcome of -19%. The middle groups earned +0.17% to +0.37%.
- **The premium isn't "free" when IV looks expensive versus recent volatility.** Puts with IV more than 1.3x realized volatility earned +0.24%, the lowest group.
- **Earnings:** I don't have a true historical earnings calendar. Using projected dates, puts spanning likely earnings earned +0.87% against +0.51% for clear windows. That doesn't support my earlier suggestion to always avoid earnings, but this test is weak.

## 8. Stock wheel backtests

### Frozen candidates on the 2022 to 2026 holdout

| | 2016-2026 | Worst drop | Sharpe | 2022-2026 | Portfolios beating SPY, 2022-26 |
|---|---|---|---|---|---|
| SPY | 14.8% | -34% | 0.74 | 11.4% | |
| QQQ | 19.4% | -35% | 0.81 | 12.6% | |
| Classic wheel | 3.4% | -32% | 0.15 | 3.8% | 0 of 40 |
| Fear wheel (VIX at least 20) | 5.6% | -23% | 0.39 | 3.6% | 0 of 40 |
| QQQ trend + Fear wheel | 14.1% | -29% | 0.73 | 7.6% | 3 of 40 |
| SPY trend + Fear wheel | 11.0% | -27% | 0.64 | 6.4% | 2 of 40 |
| QQQ trend, no options | 14.6% | -28% | 0.78 | 7.6% | 0 of 40 |
| SPY trend, no options | 11.1% | -22% | 0.76 | 7.1% | 0 of 40 |

**All wheel candidates failed.** Adding the fear wheel to a trend portfolio did not improve it.

### What improved the wheel

Tested on the watchlist version, 2017 to 2026. Its base result is 11.1% a year, -21% worst drop and a 0.71 Sharpe.

| Change | Return | Worst drop | Sharpe | Verdict |
|---|---|---|---|---|
| Calls allowed below cost | 8.1% | -21% | 0.51 | **Never do this** |
| 10-delta calls | 13.8% | -31% | 0.77 | More return, more risk |
| 15-delta calls | 12.3% | -22% | 0.78 | **Best trade-off** |
| 30-delta calls | 9.2% | -20% | 0.61 | Caps too much upside |
| 16-delta puts | 10.8% | -19% | 0.80 | **Good** |
| 35-delta puts | 9.8% | -23% | 0.60 | Worse |
| Put stop at 3x premium | 9.6% | **-14%** | **0.87** | **Best risk control** |
| Take profit at 50% | 9.4% | -19% | 0.65 | Slightly worse |
| Weekly options | 7.8% | -31% | 0.43 | **Avoid** |
| Two-month options | 10.7% | -20% | 0.70 | About the same |
| New puts only above SPY's 200-day | 8.6% | -19% | 0.57 | Worse |
| Sit out VIX above 30 | 10.6% | -21% | 0.67 | Slightly worse |
| Only VIX at least 20 | 6.7% | -15% | 0.57 | Worse |
| Double trading costs | 10.5% | -20% | 0.67 | Holds up |
| Idle cash earns 0% | 9.2% | -21% | 0.57 | T-bills matter |

These were found after the holdout, so they are leads rather than proof.

### The best wheel, year by year

| Year | Wheel | SPY | QQQ |
|---|---|---|---|
| 2017 | +7.9% | +21.1% | +32.0% |
| 2018 | **+2.0%** | -5.3% | -1.9% |
| 2019 | +22.2% | +31.3% | +38.7% |
| 2020 | +10.4% | +17.3% | +46.2% |
| 2021 | +16.4% | +30.9% | +29.6% |
| 2022 | **-8.9%** | -18.8% | -33.5% |
| 2023 | +14.1% | +27.1% | +56.9% |
| 2024 | +10.3% | +25.7% | +27.8% |
| 2025 | **+20.0%** | +18.1% | +21.2% |
| 2026 through October | **+14.6%** | +14.1% | +16.0% |

**Income:** it collected premium worth about **7.4% of the account per year**, plus T-bill interest on idle cash, across about 29 puts a year. About 21% of puts were assigned. Premium is income before stock losses, not profit.

### With Bumi

| 2016 to 2026 | Return per year | Worst drop | Sharpe |
|---|---|---|---|
| Bumi | 17.5% | -19% | 1.04 |
| Quality wheel | 9.2% | -23% | 0.68 |
| 75% Bumi + 25% wheel | 15.6% | -18% | 1.07 |
| 50% Bumi + 50% wheel | 13.5% | -19% | 1.05 |

Their daily correlation is 0.44, so the wheel diversifies a little. But every dollar moved from Bumi to the wheel lowers return, with almost no improvement in risk-adjusted return. Bumi's figures are also a backtest.

## 9. 2027 research watchlist

These are research candidates from a fixed rule, not recommendations to buy or sell. The rule, written before its test: the most liquid stocks with 60-day volatility of 20 to 60%, within 25% of their 1-year high, above their 200-day average, and with no one-day drop worse than 20% in the past year.

Data is from the November 20, 2026 close, when **VIX was near 36, so premiums are unusually high**. Quotes come from Alpaca's free indicative feed, so the spreads are unreliable. Each put is about 25 delta, 33 days out.

### Primary list: the 12 most liquid that pass

| Ticker | Sector | Price | Strike | Cash per contract | Premium | Annualized | IV | Break-even drop |
|---|---|---|---|---|---|---|---|---|
| AAPL | Technology | $342.56 | $325 | $32,500 | $536 | 18% | 36% | 6.7% |
| MSFT | Technology | $484.52 | $450 | $45,000 | $1,155 | 28% | 51% | 9.5% |
| AMZN | Consumer | $246.82 | $230 | $23,000 | $644 | 31% | 55% | 9.4% |
| LLY | Healthcare | $1,347.11 | $1,255 | $125,500 | $1,989 | 18% | 42% | 8.3% |
| MDT | Healthcare | $99.94 | $95 | $9,500 | $118 | 14% | 33% | 6.1% |
| V | Financials | $401.87 | $385 | $38,500 | $512 | 15% | 32% | 5.5% |
| WMT | Staples | $127.95 | $121 | $12,100 | $137 | 13% | 31% | 6.5% |
| XOM | Energy | $159.99 | $150 | $15,000 | $213 | 16% | 36% | 7.6% |
| JNJ | Healthcare | $270.47 | $255 | $25,500 | $328 | 14% | 33% | 6.9% |
| ACN | Technology | $221.17 | $200 | $20,000 | $458 | 25% | 62% | 11.6% |
| MA | Financials | $625.59 | $595 | $59,500 | $575 | 11% | 30% | 5.8% |
| CVX | Energy | $208.37 | $195 | $19,500 | $214 | 12% | 34% | 7.4% |

### Bench: next in line

TMO, PG, HD, ABBV, MRK, VZ, AMGN, SPOT, DHR.

### What fits your account size

- **$50k, up to 25% per position ($12,500):** MDT, WMT, MRK and VZ.
- **$100k, up to 25% per position ($25,000):** also AMZN, XOM, ACN, CVX, PG and DHR.
- **The rest need a larger account,** or a spread instead of a cash-secured put.

### Popular names that failed the rule today

NVDA, TSLA, META, GOOGL, AVGO, TSM, PLTR, NFLX and JPM are below their 200-day averages. AMD, MU, INTC, ORCL, MSTR and CRWV are also far too volatile. That is what the rule is designed to screen out, and they can re-enter at the next refresh.

**Refresh the list after November 30.** It should be regenerated each year, and a stock's place on it says nothing about whether it will rise.

## 10. If we build it: implementation map

| Stage | Work | Done when |
|---|---|---|
| **1. Data** | OPRA quotes, an earnings calendar, daily chain snapshots | Real bid/ask recorded every day |
| **2. Strategy** | Watchlist refresh, strike selection, position limits | Matches this backtest |
| **3. Trade tracking** | State machine: cash, short put, assigned, short call, called away | Handles every path in tests |
| **4. Orders** | Limit orders at mid with step-downs, roll logic, early-assignment and dividend handling | Tested on paper |
| **5. Risk** | Position and sector caps, 3x put stop, bankruptcy and halt handling | Kill switch works with Uri |
| **6. Discord** | Plan, live cards and closed cards, like Bumi | Clean for 2 weeks |
| **7. Shadow** | Record what it would trade at real quotes | Real fills match the assumptions |
| **8. Paper** | Separate Alpaca paper account | 6 to 12 months reviewed |

**Suggested starting rules:** 8 positions, 16 to 25 delta puts, about 30 to 45 days, 15-delta calls never below cost, a 3x put stop, T-bills on idle cash, and no weeklies.

## 11. Limits of this research

- **The simulator models option prices before 2024.** Only 2024 to 2026 uses real stock option prices.
- **Survivorship is reduced, not eliminated.** Alpaca's list omits many delisted tickers, so I added known failures by hand.
- **Historical bid/ask is unavailable.** Fills are estimated from traded prices and a fixed penalty.
- **Early assignment and dividends** are simplified, and **taxes are ignored.** Short-term option income is usually taxed less favorably than long-term stock gains.
- **The improvements in sections 7 and 8 came after the holdout was used,** so expect them to shrink.
- **Results depend on the period.** 2016 to 2026 was a strong bull market, which is the wheel's worst environment.

## 12. Open questions

1. Do real OPRA spreads match the 5% fill assumption?
2. Does a true earnings calendar change the earnings result?
3. Would paid historical option data, including delisted stocks, confirm the 2016 to 2023 results?
4. Could selling puts only on stocks you would own anyway improve after-tax results compared with buying them outright?
5. Does put-selling in a tax-advantaged account change the comparison?
6. Would defined-risk put spreads make expensive stocks affordable without worse returns?
7. Can the 200-day filter and a 3x stop together reduce drawdowns without giving up too much return?

## 13. Recommendation

**Don't build the wheel to beat the market.** The evidence is consistent across 30 years of real index data, real 2024 to 2026 option prices and the stock simulator.

There are two reasonable paths from here:

- **Keep capital in Bumi and shelve the wheel.** This best fits your stated rule that it must beat buy-and-hold.
- **Build it as a separate, income-focused paper bot,** accepting that it will probably trail SPY in strong years. This fits only if steady monthly premium and smaller drawdowns matter more to you than maximum return.

I'd take the first path unless the income itself is the goal.
