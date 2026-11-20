# Snap: index ETF dip-buyer (strategy id `snap`)

Found by the research lab on 2026-11-20, when the user asked for a fully objective strategy (no discretion) that is "truly profitable over the data we have". **Backtest only. No live bot runs it yet.**

## The rules
All on daily bars. Signals are read at the close and filled at the close, with a market-on-close order sent a minute before the bell.

| | |
|---|---|
| **Universe** | QQQ, SPY, IWM, DIA |
| **Buy** | at the close, when the close is above its 200-day average **and** either the 2-day RSI is under 10 **or** the close is in the bottom 10% of the day's range (IBS < 0.1) |
| **Sell** | at the first close above the 5-day average, or after 20 trading days |
| **Stop** | 3 × ATR(14) below the entry, checked against each day's low. If price gaps through it, the fill is at the open. |
| **Size** | the stop loses 1% of a $50k account; no position is bigger than 2× the account |
| **Limits** | one position per ETF; at most 4 open at once |

Code: [app/strategies/snap.py](../app/strategies/snap.py) and [config/strategies/snap.json](../config/strategies/snap.json). Backtest with `python -m app backtest --strategy snap --from 2016-01-01 --to 2026-10-31 --label …`.

## How it was found (and why it should be trusted)
The **pass bar was fixed before any testing**:
- Ideas were built and tuned on **2021–2023** only.
- A finalist got **one look** at the untouched **2024–2026**.
- To pass, after costs, it needed all of:
  - a profit factor of at least 1.3 in both periods
  - 100+ trades
  - most years positive
  - a worst drawdown under $10k

**Ideas tried:**

| Idea | Result | Verdict |
|---|---|---|
| Daily mean reversion on ETFs (RSI(2), IBS, 3 down days, turn of the month) | the index ETFs worked best | → Snap |
| Overnight holding (close to next open) | profit factor about 1.0–1.1 on 2021–2023 | dropped |
| Intraday "noise area" momentum (Zarattini et al. 2024) on QQQ, SPY, MNQ and MES | MNQ with hourly checks was the best, run #69 | **near miss**: profit factor 1.48 on 2021–2023 but 1.29 on 2024–2026; every year 2020–2026 positive |

**Snap's one look at 2024–2026 (run #70) passed:**

| | Trades | Profit factor | Total |
|---|---|---|---|
| 2021–2023 (built on) | 188 | 1.37 | +$5.0k |
| **2024–2026 (untouched)** | **240** | **2.58** | **+$15.4k** |
| 2016–2020 (earlier history, never used for tuning) | — | 1.40 | +$7.7k |

**By year:**

| 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|
| +0.2k | +7.0k | **−2.4k** | +1.5k | +1.4k | +3.4k | **−0.5k** | +2.1k | +6.6k | +4.1k | +4.7k |

**Overall:**
- **Worst drawdown:** −$2.3k from 2021–2026.
- **Every ETF is profitable on its own:**

  | QQQ | SPY | IWM | DIA |
  |---|---|---|---|
  | 2.31 | 1.69 | 1.39 | 1.37 |

  (profit factor over 2016–2026)
- **Baseline:** run #71, 2016-01 to 2026-10: 707 trades, +$28.6k, a profit factor of 1.69, and a worst drawdown of −$4.1k (in 2018).
- **The live-plan variant, run #74** (decide after the close, trade at the next open): 721 trades, +$29.0k, a profit factor of 1.67, and a worst drawdown of −$5.2k. It also passes the bar. Turn it on with `--set fills.mode="next_open"`.

## The same rules on 18 ETFs it never saw
Unchanged rules, 2016–2026. **17 of 18 are profitable.**

| | Profit factor |
|---|---|
| Strongest | VOO 1.98 · XLK 1.99 · VTI 1.95 · IVV 1.85 · XLI 1.68 · MDY 1.65 |
| Weakest | EWU 1.11 · EWJ 1.12 · XLY 1.20 |
| Only loser | **XLV (healthcare) 0.96** |

So the effect is general to equity index ETFs, not a fit to four tickers.

## Stress tests (after the one look, so they're for robustness, not selection)

| Change | 2021–2023 PF | 2024–2026 PF | Bar |
|---|---|---|---|
| Slippage 2 bp each way | 1.33 | 2.49 | passes |
| Slippage 5 bp each way | 1.18 | 2.24 | fails (2021–2023) |
| Fill at the next open instead of the close | 1.58 | 1.92 | passes |
| RSI under 5 / under 15 | 1.46 / 1.27 | 3.20 / 2.00 | passes / fails |
| IBS under 0.05 / 0.15 | 1.37 / 1.44 | 3.07 / 1.94 | passes |
| Stop 2 / 4 × ATR | 1.32 / 1.80 | 1.91 / 2.65 | passes |
| Exit above the 3-day / 10-day average | 1.36 / 1.19 | 2.84 / 2.23 | passes / fails |
| Trend filter: 100-day average | 1.52 | 3.31 | passes |

Every neighbouring setting is profitable in every period. Real slippage on these ETFs is well under 1 bp.

## Honest caveats
- **The returns are modest:** about +$2.6k a year on $50k (around 5%) at 1% risk, and the stop is rarely hit. A larger risk per trade scales the profits and the drawdowns together.
- **It tends to lose in bear years** (2018, 2022). The 200-day filter keeps it out of the worst of those.
- **2024–2026 was a strong bull market,** which suits dip-buying. Over 2016–2023 the profit factor is about 1.4.
- **It needs a margin account:** with all 4 ETFs open it can use up to about $103k of buying power.

## Next steps (not done)
1. **Paper trading on Alpaca:** a bot like Orbi that sends market-on-close orders at 3:59 PM ET.
2. **A Discord name and avatar,** and an announcement in the bots channels.
3. **Optional second engine:** the MNQ momentum near miss (run #69), which needs a futures broker.
