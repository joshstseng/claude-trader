# Scalp Research: VWAP and EMA Pullbacks (2026-11-24)

## Verdict
**No genuine scalp edge was found in VWAP or EMA pullbacks.** One variant (EP5) passed the pre-set bar in every
window, but a control test showed its profit comes from Swing v1's direction filter, not from the pullback. Random
entries in Swing's direction did as well. It's weaker than Swing and 0.6-0.7 correlated with it, so it adds nothing
as a separate bot.

## What was tested
- **Data:** QQQ 1-minute bars (Alpaca SIP, adjusted), regular session, 2,702 full sessions, 2016 to October 2026.
- **Protocol:** rules frozen in writing before each round (`app/research/scalp/FROZEN_SCALP.md`). Choices made on
  2016-2019 only, one look at 2020-2022, one look at 2023-October 2026.
- **Execution:** completed bars only, entry at the next 1-minute open, stop beats target inside a bar.
- **Costs:** 0.6 bp per side plus 0.3 bp on stops (about twice MNQ's real cost). Stress test at double.
- **Bar:** positive after costs, profit factor at least 1.10, Sharpe at least 0.8 at 0.25% risk a trade, still
  profitable at double costs, most years positive, at least 300 trades.

## Results
| Round | Idea | Variants | Positive after costs | Cleared the bar | Backtest |
|---|---|---:|---:|---:|---|
| 1 | VWAP and EMA 9/20 pullbacks, 1m and 5m | 160 | 2 | 0 | #80 |
| 2 | Same, only in Swing v1's direction | 40 | 8 | 0 | #81 |
| 3 | EMA, Swing direction, larger minimum stops | 36 | 25 | 2 | #81 |
| 4 | VWAP fade while Swing is flat | 24 | 0 | 0 | #83 |
| SPY | Round 1 grid on SPY instead of QQQ | 160 | 21 | 0 | #85 |

Before costs the pullbacks earned about +0.05 to +0.10R a trade, and costs took about 0.1R. 1-minute versions were
worse than 5-minute versions in every round. The SPY check shows the failure isn't specific to QQQ.

### EP5, the one that passed
5-minute EMA 9/20 pullback, only in Swing v1's direction, swing-low stop of at least 0.15%, 3R target, flat by 3:55.

| Window | Trades | Avg R | PF | Sharpe | At double costs |
|---|---:|---:|---:|---:|---:|
| Dev 2016-2019 | 573 | +0.115 | 1.21 | 0.91 | |
| Validation 2020-2022 | 528 | +0.101 | 1.17 | 0.94 | +0.057 |
| Final 2023-Oct 2026 | 607 | +0.086 | 1.15 | 0.81 | +0.036 |

**Why it isn't worth building** (backtests #82 and #84):
1. **The pullback adds nothing.** Entering at any 5-minute close in Swing's direction did as well: +0.101R, +0.162R
   and +0.079R across the three windows. EP5 beat only 62% of 200 random Swing-direction entry sets.
2. **It overlaps Swing.** Daily correlation was 0.6-0.7. In the final window it made 3.4% a year versus Swing's 9.3%,
   and adding it to Swing lowered the Sharpe from 1.36 to 1.27.
3. **A few days carry it.** The top 10 days were 86% of final-window profit. Without them it made +0.012R a trade.
4. **It isn't really a scalp.** The median trade lasted 85 minutes, and 36% were still open at 3:55.

## Outside evidence
I found no independent after-cost backtest of either setup. The public material is TradingView scripts and
educational pages without out-of-sample results. The one academic source (Zarattini and Aziz, VWAP trend following on
QQQ) is a trend strategy close to what Swing already does, not a pullback scalp.

## Recommendation
Don't build a VWAP or EMA pullback scalp bot. The edge in this data is Swing's: being on the right side on the
Nasdaq's breakout days. Better uses of time are Swing's live paper results, and real MNQ execution data when a
futures account is available.

Code: `app/research/scalp/`. This is strategy research, not personal financial advice.
