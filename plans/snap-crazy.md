# Snap: extreme variants (exploration)

Written 2026-11-20. The user asked for "extremely crazy parameters" to see if anything interesting turns up. **Snap itself is unchanged.**

**Setup:**
- Engine: [app/research/crazy.py](../app/research/crazy.py)
- QQQ, SPY, IWM and DIA, January 2016 to October 2026
- Entry at the next open; 1% risk to a 3 × ATR stop unless noted; 1 bp slippage
- If the stop and target are both hit the same day, the stop counts first

**Read with care:** every year has been looked at, so these are **leads to verify** (on paper, or on new data), not proof. "True drawdown" counts open losses day by day, not just closed trades.

## Headline findings
| Variant | Trades | Win rate | PF | Profit | True drawdown | Profit ÷ drawdown | Years positive |
|---|---|---|---|---|---|---|---|
| **Snap baseline** (sell above the 5-day average) | 721 | 70% | 1.67 | +$29.0k | −$5.6k | 5.2 | 9/11 |
| **1 × ATR trailing stop only** | 813 | 46% | 1.69 | +$37.4k | **−$3.7k** | **10.1** | 9/11 |
| 1 × ATR trailing stop, plus scaling in | 813 | 44% | 1.71 | +$39.8k | −$4.3k | 9.3 | 9/11 |
| 3R target only (60-day limit) | 195 | 53% | 2.18 | +$55.0k | −$7.7k | 7.1 | 10/11 |
| No trend filter, sell when the 2-day RSI is above 70 | 888 | 71% | 1.61 | +$41.1k | −$6.0k | 6.9 | 10/11 |
| **3R target, plus scaling in** | 195 | 54% | 2.39 | **+$107.1k** | −$15.5k | 6.9 | 10/11 |

**Profit factor by period:**

| Variant | 2016–20 | 2021–23 | 2024–26 |
|---|---|---|---|
| Snap baseline | 1.41 | 1.65 | 2.24 |
| 1 × ATR trailing stop only | 1.49 | 1.98 | 1.76 |
| 1 × ATR trailing stop, plus scaling in | 1.49 | 2.01 | 1.77 |
| 3R target only | 2.19 | 1.96 | 2.37 |
| No trend filter, RSI above 70 exit | 1.44 | 1.51 | 2.10 |
| 3R target, plus scaling in | 2.44 | 1.90 | 2.82 |

## What we learned
1. **Snap's 5-day-average exit leaves money on the table.**
   - Trailing a stop 1 × ATR under the best price, with no other exit, makes more (+$37k against +$29k) with a smaller true drawdown (−$3.7k against −$5.6k).
   - Combining the trail *with* the 5-day-average exit is worse (+$15.7k).
2. **Letting winners run to fixed targets** (2R, 3R, 5R) roughly doubles the profit, with a profit factor of 2.0–2.3 in every period.
   - Part of this is just more time in a rising market: average holds are 30–35 days against Snap's 3.
   - The true drawdown is a bit higher, about −$8k.
3. **Scaling in on a second signal** adds profit, but it's really just doubling the size. With a 3R target it's +$107k, but the drawdown is −$15.5k, over our $10k limit.
4. **The 200-day trend filter isn't essential.** Without it there are more trades and slightly more profit, with 10 of 11 years positive.
5. **Buying crashes** (only when below the 200-day average, no stop) is surprisingly steady: a profit factor of 1.7–2.0 in every period. It's small money (+$10k, true drawdown −$4.4k).
6. **Traps:**
   - **No stop, sell only once in profit:** it looks amazing (profit factor 4.89, 84% winners), but its true drawdown is −$17.7k, one trade sat −$5.4k (11R) underwater, and holds ran to 250 days.
   - **Shorting rips in an uptrend:** loses −$13.1k.
   - **Very extreme entries** (2-day RSI under 2, gaps of more than 2%): too few trades, no edge.
   - **Tight stops with small targets** (0.5R or 1R with a 1 × ATR stop): about break-even.

## Full results
**Exits and targets (Snap's entry):**

| Variant | Trades | PF | Profit | Closed-trade drawdown |
|---|---|---|---|---|
| Target 0.25R | 690 | 1.57 | +$28.2k | −$3.8k |
| Target 0.5R | 536 | 1.61 | +$39.8k | −$6.1k |
| Target 1R | 356 | 1.76 | +$49.8k | −$6.5k |
| Target 2R | 222 | 1.99 | +$52.4k | −$6.9k |
| Target 3R | 195 | 2.18 | +$55.0k | −$5.6k |
| Target 5R | 172 | 2.29 | +$51.2k | −$5.1k |
| 0.5R target, 1 × ATR stop | 990 | 1.08 | +$12.3k | −$16.5k |
| 1R target, 2 × ATR stop | 570 | 1.47 | +$56.0k | −$9.0k |
| Trail 2 × ATR only | 553 | 1.70 | +$44.4k | −$5.7k |
| Trail to the prior day's low only | 753 | 1.66 | +$37.7k | −$4.9k |
| Break-even at 1R, plus the 5-day exit | 722 | 1.68 | +$29.1k | −$5.6k |
| Hold exactly 1 day | 914 | 1.39 | +$15.4k | −$3.1k |
| Hold exactly 3 days | 722 | 1.70 | +$34.9k | −$4.7k |
| Hold exactly 5 days | 636 | 1.74 | +$41.0k | −$4.7k |
| Hold exactly 10 days | 486 | 1.70 | +$45.3k | −$5.6k |
| Hold exactly 20 days | 338 | 1.82 | +$44.5k | −$8.1k |
| Exit when the 2-day RSI is above 70 | 677 | 1.72 | +$35.7k | −$3.9k |
| Exit above the 10-day average | 702 | 1.57 | +$29.5k | −$5.4k |
| Exit on the first up close | 818 | 1.51 | +$20.6k | −$5.5k |

**Entries (Snap's exit):**

| Variant | Trades | PF | Profit | Closed-trade drawdown |
|---|---|---|---|---|
| 2-day RSI under 5 only | 202 | 1.73 | +$10.8k | −$3.1k |
| 2-day RSI under 25 only | 759 | 1.42 | +$23.5k | −$8.4k |
| IBS under 0.05 only | 332 | 1.90 | +$15.8k | −$3.2k |
| IBS under 0.2 only | 973 | 1.51 | +$29.0k | −$4.8k |
| 5 down closes in a row | 64 | 1.94 | +$3.9k | −$0.8k |
| A single-day drop of more than 2% | 172 | 1.58 | +$7.9k | −$3.1k |
| Only when all 4 ETFs signal the same day | 253 | 2.35 | +$17.7k | −$3.4k |
| Short rips below the 200-day average | 237 | 1.28 | +$4.3k | −$3.1k |

## Is the trailing stop a lucky setting? (robustness)
Snap's entry, with only the trailing stop as an exit:

| Starting stop | Trail | Trades | PF | Profit | True drawdown | Years positive |
|---|---|---|---|---|---|---|
| 3 × ATR | 0.5 × ATR | 896 | 1.48 | +$21.4k | −$5.9k | 8/11 |
| 3 × ATR | **1 × ATR** | 813 | 1.69 | +$37.4k | **−$3.7k** | 9/11 |
| 3 × ATR | 1.5 × ATR | 679 | 1.51 | +$33.1k | −$5.7k | 10/11 |
| 3 × ATR | 2 × ATR | 553 | 1.70 | +$44.4k | −$6.5k | 9/11 |
| 3 × ATR | 3 × ATR | 331 | 1.96 | +$48.0k | −$7.9k | 9/11 |
| 2 × ATR | **1 × ATR** | 820 | 1.71 | **+$57.6k** | −$5.9k | **10/11** |
| 2 × ATR | 2 × ATR | 560 | 1.73 | +$69.3k | −$9.0k | 9/11 |
| 2 × ATR | 3 × ATR | 363 | 1.89 | +$70.1k | −$12.7k | 10/11 |

**Every trail from 0.5 to 3 × ATR is profitable in every period** (2016–20, 2021–23, 2024–26), so it isn't a lucky number.

**1 × ATR is the sweet spot.** With a 2 × ATR starting stop (bigger positions for the same 1% risk), it makes **about twice Snap's profit (+$57.6k against +$29.0k) for about the same drawdown (−$5.9k against −$5.6k).**

## Worth verifying next
1. **The 1 × ATR trailing stop instead of the 5-day-average exit,** ideally with a 2 × ATR starting stop. It's the cleanest improvement: more profit at about the same drawdown, and robust to the trail distance. It would need paper trading, or new data, to confirm.
2. **A 2R or 3R target** as a "more return, a bit more risk" version.
