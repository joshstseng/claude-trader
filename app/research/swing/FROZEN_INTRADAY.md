# Intraday and hourly research rules, frozen before any intraday result (2026-11-22)

Data (changed before any result, because HistData's TLS certificate expired and verification stays on): free Dukascopy hourly bid candles, 2012 to October 2026, for EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, gold, WTI, S&P 500 and Nasdaq-100, plus Alpaca 5-minute SIP bars from 2016 for SPY, QQQ, IWM, GLD, SLV, USO, FXE, FXY, FXB, FXA and TLT.
Dukascopy prices are spot/CFD-style stand-ins for M6E, MJY, M6B, M6A, MCD, MGC, MCL, MES and MNQ. They are not exchange futures prices.

## Windows
- Develop: 2012-2019. Free to explore.
- Validate: 2020-2022. Only for candidates chosen on develop.
- Final: 2023 to October 2026. Run once per frozen candidate, at most three candidates in total.

## Costs, per contract per side
One full tick of slippage plus $0.75 fees: MES $2.00, MNQ $1.25, MGC $1.75, MCL $1.75, M6E $2.00, MJY $2.00, M6B $1.50, M6A $1.75, MCD $1.75.
Stops fill at the stop or worse. If a bar touches both stop and target, the stop is assumed to hit first. Entries occur after the signal bar closes.

## A candidate passes only if all of these hold on the final window
1. Net Sharpe is at least 0.7 and net profit is positive at 1x costs.
2. Net profit is still positive at 2x costs.
3. At least 100 trades.
4. At least three of the four calendar years 2023-2026 are profitable.
5. No single year supplies more than 60% of total profit.
6. It either beats buy-and-hold of the same market on Sharpe, or has correlation below 0.3 to SPY and improves a portfolio with SPY.
7. It also made money on validate.

If a candidate fails, it is rejected and not re-tuned on the final window. All variants tried are counted and reported.

# Candidate 1, frozen after the 343-variant dev screen and before reading 2020+
Nasdaq noise-band breakout on QQQ 5-minute bars, standing in for MNQ, regular session only, both directions, flat by the close.
- Band = average absolute move from the open at that time of day over the prior 14 sessions, 1.0x, around max/min of today's open and yesterday's close.
- Checked every 30 minutes on completed bars. Enter or flip outside the band at the next bar's open. Exit when price returns inside the band.
- Size = 1% daily volatility target, capped at 2x notional. Cost 0.6 bp per side.
This is the standard 14-day setting, not the best-scoring neighbor (dev Sharpe 1.03; the best was 1.14).
Validate requirement: positive net profit in 2020-2022 at 1x and 2x costs.

Results: validate passed (7.6%/yr, Sharpe 1.17). Final passed all seven rules on QQQ (9.6%/yr, Sharpe 1.41, -7.6%).
After the final test, whole-contract MNQ on index prices showed less: 4.2%/yr at $100k and 5.2%/yr at $250k on matching days. No settings were changed.

# Candidate 2, frozen after a 777-variant hourly dev screen and before reading 2020+ for this rule
Long-only multi-day hourly breakout on SPY, QQQ, IWM, GLD, SLV, USO and TLT, all seven with no market removed (stand-ins for MES, MNQ, M2K, MGC, SIL, MCL, ZN/UB).
- Enter long at the next hourly open after an hourly close above the highest high of the prior 70 hourly bars (10 sessions).
- Stop and chandelier trail: 3 ATR(70 hourly bars). Time limit: 350 hourly bars. Risk 0.5% per trade, capped at 2x notional per market.
- Portfolio = sum of market returns x 1.5 / sqrt(7).
Dev: 5.0%/yr, Sharpe 1.03, -4.9%, corr to SPY 0.14. Middle settings were used, not the best-scoring market or neighbor.
Validate gate: positive at 1x and 2x costs in 2020-2022. Only then may the final window run, against the same seven rules. For rule 6 the test is corr to SPY below 0.3 and SPY + strategy Sharpe above SPY.

Result: passed with fractional sizing, including T-bill financing (final 4.2%/yr, Sharpe 0.74). REJECTED for real accounts: in whole micro contracts the final window made -1.1%/yr at $50k, 1.0% at $100k, and 1.9% at $250k (Sharpe -0.57, 0.33, 0.46).

# Candidate 3, frozen before reading its results: candidate 1's rule outside US hours
No parameter changes: 14-session band, 1.0x, 30-minute checks, same sizing. Session opens at 6:00 PM ET and exits at 2:00 AM ET (Asia), or opens at 2:00 AM ET and exits at 9:25 AM ET (London/pre-market). Nasdaq-100 and S&P 500 index-CFD prices, 2020 to Oct 2026, 1 bp per side.
It passes only if 2020-2022 and 2023-Oct 2026 each have Sharpe >= 0.7, positive profit at 2x costs, and 100+ trades.
