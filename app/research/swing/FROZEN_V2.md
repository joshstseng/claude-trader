# Swing v2 rules, frozen before any v2 result (2026-11-22)

Swing v1 stays unchanged as the baseline. v2 keeps v1's 30-minute breakout signal, exits, flips, sizing and 4:00 PM flat rule. Only the entry changes.

## Entry idea
After a v1 breakout signal, wait up to 15, 30 or 60 minutes for a pullback on 1-minute or 5-minute bars.
- Oscillator pullbacks: RSI(2) below 10 or 20, RSI(7) or RSI(14) below 30 (mirrored for shorts), then enter at the next bar's open. Price must still be beyond the band.
- Reversal confirmation: an RSI(2) reading below 20, followed by a close above the prior bar's high (mirrored for shorts).
- Limit pullbacks: touch of the band, EMA(9), EMA(20), VWAP, or a 38.2%, 50% or 61.8% retrace of the prior 30 minutes' move.
- If no pullback comes: either skip the trade or enter at market when the wait ends.
- If a 30-minute check returns inside the band while waiting, the setup is cancelled.

## Fill assumptions
Limit orders fill only if price trades through the level by 0.2 bp. Gaps fill at the worse open. Limit entries pay the same 0.6 bp per side as market entries.

## Selection
- Choose on 2016-2019 only. A variant is eligible if its Sharpe beats v1 (1.03), it is profitable at 2x costs, and it has 100+ trades.
- Freeze at most three: the best-scoring eligible variant from each of the three entry groups (oscillator, reversal, limit).
- Validate on 2020-2022: Sharpe must beat v1 on the same data.
- Final on 2023 to October 2026, run once: Sharpe AND annual return must both beat v1, and it must stay profitable at 2x costs.
- This data was already seen while developing v1, so even a pass is weaker evidence than v1's original final test.

## Result
No candidate. 0 of 144 variants beat v1's 1.03 Sharpe on 2016-2019 (best 0.94), so none was frozen and v2 was not run on 2020-2022 or 2023-2026.
Follow-up on 2016-2019 only: v1 trades that pulled back to the band within 15 minutes averaged -2.0 bp, and those that did not averaged +9.5 bp.
A half-at-breakout, half-at-band entry had Sharpe 1.07 and a -5.7% worst drop (v1: 1.03, -10.0%), but returned 5.83%/yr vs 7.66%, so it does not meet the return requirement.
