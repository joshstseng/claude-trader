# Asia Session Research: Forex and Gold (2026-11-24)

## Verdict
**No genuine Asia-session edge was found after costs** in USD/JPY, AUD/USD, EUR/USD or gold (the stand-in for MGC).
302 variants were tested across four strategy families. Two real effects showed up, but neither is tradable:
- **The Gotobi fix trade** (buy USD/JPY into the 9:55 Tokyo fix on settlement days) worked in 2016-2019 but lost money
  in 2020-2022.
- **Asian moves do revert**, but by only about 1 bp a trade, which is roughly what retail spreads cost.

Trading with the trend inside the Asia session lost money in every form tested.

## Data and method
- **Data:** HistData free 1-minute bid bars, 2016 to October 2026, about 2,800 Asia sessions per instrument.
  The timestamps turned out to be New York time with daylight saving; that was caught and fixed before any validation.
- **Session:** 9:00 AM to 5:00 PM Tokyo (7 PM to 3 AM EST).
- **Costs per side:** 0.5 bp on USD/JPY and EUR/USD, 0.8 bp on AUD/USD and gold, plus 0.3 bp on stops.
- **Protocol:** rules frozen in writing before each round (`app/research/scalp/FROZEN_ASIA.md`). Choices on 2016-2019,
  one look at 2020-2022, one look at 2023-October 2026. The same bar as the Nasdaq scalp research.

## Results
| Round | Idea | Variants | Positive after costs | Result | Backtest |
|---|---|---:|---:|---|---|
| A | Trend pullbacks: EMA 9/20 or TWAP, daily or 1h trend | 96 | 2 | best Sharpe 0.27 | #86 |
| A | Tokyo fix trades (dollar up into 9:55) | 12 | 3 | Gotobi USD/JPY passed dev, failed validation | #86, #87 |
| A | Gold drifts up in Asian hours | 2 | 0 | | #86 |
| B | Noise-band breakout (Swing's idea) | 64 | 3 | best Sharpe 0.15 | #88 |
| B | First-hour momentum | 32 | 3 | best Sharpe 0.29 | #88 |
| C | Fade stretched moves, optionally only against the daily trend | 96 | 0 | positive before costs only | #88 |

**Gotobi trade:** 2016-2019 +1.45 bp a trade, PF 1.34, Sharpe 0.86. 2020-2022 -1.07 bp, PF 0.78, every year negative.

**Asia fade before costs:** Sharpe up to 2.0 on EUR/USD and 1.5 on AUD/USD, but only +0.8 to +1.2 bp a trade.
That breaks even at about 0.4-0.6 bp per side.

## What this means
- The Asia session behaves like a range. Following moves loses, and fading them works only before costs.
- A fade might pay with institutional costs well under 0.4 bp per side. That isn't realistic for this account.
- Real MGC futures data was not used. Spot gold behaved like the forex pairs, so MGC is unlikely to differ much.

## Sources
- Krohn, Mueller and Whelan, Bank of Canada Staff Working Paper 2021-48, on dollar moves around currency fixes.
- Bessho, Sugimoto and Suzuki (2023), arXiv 2301.13204, on the Gotobi anomaly.
- Copenhagen Business School thesis "Gold Price Dynamics Around the Clock," on gold in Asian hours.

Code: `app/research/scalp/asia.py` and `x20`-`x25`. This is strategy research, not personal financial advice.
