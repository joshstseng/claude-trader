# Swing v1 improvement tests, frozen before any result (2026-11-22)

Swing v1 stays unchanged as the baseline. These tests are run on QQQ first, using the same sizing and costs.

## Test groups
1. Exits: tighter of band or VWAP, VWAP only, opposite band only, hold to the close, and trailing exits from the best price since entry.
2. Timing: 15-minute and 60-minute checks against v1's 30-minute checks, using the same check interval for entries and exits.
3. Red-folder news: FOMC, CPI, jobs report and PPI days, both skipping them and trading only them, including flat-until-release versions where the release time allows it.

## Selection
- Choose on 2016-2019 only.
- A variant advances if its Sharpe beats v1 on 2016-2019, it is profitable at 2x costs, and it has 100+ trades. A skip-news rule advances on the same test.
- At most one finalist per group: the highest 2016-2019 Sharpe.
- 2020-2022 gate: Sharpe must beat v1 on the same days.
- 2023 to October 2026, run once: Sharpe and annual return must both beat v1, and it must stay profitable at 2x costs.
- Results that fail a gate are reported as failed and are not re-tuned.

## Evidence limit
These years were already seen while developing v1, so even a pass is weaker than v1's original final test. Any change must also prove itself in the live shadow test before replacing v1.

## Results: Swing v1 stays unchanged
- Exits: finalist 0.25x daily-volatility trail. 2016-19 9.4%/yr, Sharpe 1.44; 2020-22 8.0%, 1.27; 2023-Oct 2026 8.3%, 1.30 vs v1 9.6%, 1.41. FAILED final. The next setting, 0.5x, had only Sharpe 0.82 on 2016-19.
- Timing: finalist 15-minute checks. 2016-19 9.1%/yr, Sharpe 1.14; 2020-22 4.4%, 0.62 vs v1 7.6%, 1.17. FAILED validate. 60-minute checks did not beat v1 on 2016-19 (best Sharpe 1.00).
- News: finalist skip FOMC days. 2016-19 8.6%/yr, Sharpe 1.17; 2020-22 7.5%, 1.17; 2023-Oct 2026 8.9%, 1.36 vs v1 9.6%, 1.41. FAILED final. Skipping all red-folder days had Sharpe 0.91 on 2016-19.
- Jobs-report days were v1's strongest event: 34% of 2016-19 profit and 23% of 2023-Oct 2026 profit.
- News dates: CPI, jobs and PPI from ALFRED release lists; scheduled FOMC decisions from Federal Reserve calendars. Unscheduled March 2020 meetings are excluded.
