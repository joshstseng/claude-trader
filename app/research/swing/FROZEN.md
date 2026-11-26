# Frozen before the 2019-2024 holdout was read (2026-11-22)

System: long/short trend sleeve, 18 markets (S&P, Nasdaq, Russell, Dow, gold, silver, copper, crude, EUR, GBP, AUD, JPY, CAD, CHF,
10-year, corn, soybeans, wheat). Forecast is the mean of EWMAC 16/64, 32/128, 64/256, risk-weighted equally by asset group, 15% target
volatility, $50k fixed capital, whole micro or mini contracts. One-day execution delay. Full spread plus $1.50 per contract per side.

Tested as: S&P futures + 0.5 x trend sleeve, against S&P futures alone.

Trials before this point: about 330 variants. The sleeve was the first idea tested, but its blend with carry failed validation.

It passes only if ALL hold on 2019-01-01 to 2024-03-28:
1. Trend sleeve net Sharpe >= 0.30.
2. S&P + 0.5 x trend has a higher return AND a higher Sharpe than S&P alone.
3. Its worst drawdown is no worse than S&P alone.
4. Conditions 1 and 2 still hold at 2x costs.

If it fails, it is rejected. No settings get changed and re-run on this holdout.

Result: passed all four. Sleeve 7.1%/yr, Sharpe 0.64. S&P + 0.5 trend 18.5%, Sharpe 0.97, -30.8% vs S&P 14.2%, 0.79, -34.8%.
Caveat: 2022 supplied much of the gain, and the 0.5 sleeve was scaled from a $50k run rather than sized in whole contracts.

## Forward check, frozen before reading 2024-04-01 to 2026-11-20
Roll-adjusted futures end in March 2024, so this uses ETF proxies (SPY, QQQ, IWM, DIA, GLD, SLV, CPER, USO, FXE, FXB, FXA, FXY, FXC, FXF, IEF, CORN, SOYB, WEAT)
minus T-bills, with the same forecast, weights and 15% target, and costs of 3 bp per side. No setting changes.
It passes if the sleeve's return over T-bills is positive and S&P + 0.5 x trend has a Sharpe no lower than S&P alone.

Result: FAILED. Sleeve -1.5%/yr over T-bills, Sharpe -0.11. S&P + 0.5 trend Sharpe 0.47 vs S&P 0.54. The trend sleeve is rejected and will not be re-tuned.

# Second candidate, frozen before reading 2019+: Nasdaq overnight hold
Picked as the only one of 13 overnight markets with Sharpe >= 0.5 in both dev (0.46 rounds short) and val (0.62), so it is a weak pre-test pass and selection bias is likely.
Rule: long QQQ from the 4:00 PM close to the next 9:30 AM open, flat in US hours, 1.5 bp per side. All returns are over T-bills.
Passes only if, on BOTH 2019-01-01..2024-03-28 and 2024-04-01..2026-11-20 separately:
1. Sharpe is above buy-and-hold QQQ.
2. Return over T-bills is positive.
3. Condition 1 still holds at 3 bp per side.
No changes or re-runs if it fails.
