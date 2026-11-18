# Live checklist: what to look at each market day

For the Step 1a gate (5 clean days in a row, Nov 18 → earliest Nov 24) and the Step 1b gate (2–3 weeks of paper trading, ≥20 approved trades). Times are **Pacific** (your time); New York is 3 hours ahead.

**The one rule:** you shouldn't have to fix anything by hand. If you do, the day doesn't count toward the gate, and that's exactly what we want to find.

---

## Each morning

| Time (PT) | Where | What you should see | Note it if… |
|---|---|---|---|
| ~5:30 AM | `#system` | 📋 **focus list ready: ~200 stocks** | it's missing, or there's a ⚠️ instead (e.g. Yahoo blocking Railway) |
| 6:51–8:31 AM | `#setups` | Alerts that **@mention you**. Each one has entry, stop, target, shares, risk. Up to 5 a day | no alerts at all on a busy market day; anything that looks wrong (stop above entry, odd share counts, a stock under $5) |
| within 5 min of an alert | the alert | Tap **Approve** (or Skip). Lines appear under it: ⏳ **Order sent** → 🟢 **Bought** (or ⌛ not filled, cancelled) | Approve says ⛔ **Not placed** and the reason doesn't make sense to you |
| ~8:31 AM | `#system` | 🏁 **scan window closed: X signals, Y alerts** | missing |

## During the day

| When | Where | What you should see | Note it if… |
|---|---|---|---|
| if a stop or target hits | `#trades` + under the alert | ❌ **Stopped out** or ✅ **Target hit**, with $ and R | a position closed in Alpaca but nothing showed up |
| anytime | `/positions` | open positions, open orders, today's $5k account | it doesn't match what Alpaca shows |
| 12:55 PM (3:55 ET) | `#trades` | 🏁 **out for the day**: anything still open is sold (➖ flat) | anything is still open after this |
| 12:58 PM | `#system` | nothing (silence = good) | a ⚠️ **Still open** ping |

## After the close

| Time (PT) | Where | What you should see | Note it if… |
|---|---|---|---|
| ~1:15 PM | `#daily-summary` | Results for every signal (✅ ❌ ➖), alerted vs all vs your picks; **Paper trades (real fills)** with real vs backtest; 💸 costs; all-time P&L; 🔎 **data check** ("X of Y live signals confirmed") | missing; the data check confirms less than ~80%; a paper trade's real result is very different from "backtest said…" |
| anytime | `/pnl` | all-time paper P&L, recent days, costs measured so far | numbers don't match the daily summaries |

## Anytime

- **⚠️ anything in `#system` with an @mention** → note the time and the message. That's the bot telling you something broke.
- **🔴 bot stopped without a 🟢 online right after** → the bot is down. (A 🔴 then 🟢 pair is just a redeploy.)
- **Emergency:** `/flatten confirm:yes` closes everything and pauses. `/resume` turns it back on.

## What to write down

Keep it short. For each day:
1. **Date** · did everything arrive on its own? (yes / what was missing)
2. **Alerts:** how many; which you approved; did they fill?
3. **Anything that looked wrong or confusing** (screenshots help)
4. **Data check** line from the daily summary (e.g. "9 of 11 confirmed")
5. **Paper P&L** for the day

Bring the notes back to Claude. Problems found here are the point of the gates.
