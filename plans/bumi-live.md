# Bumi: going live with real money

**Don't start this until Bumi has passed paper:** about 2–3 months, at least 3 real rebalances, and fills within about
0.1% of the official open (Uri's Friday weekly check shows this). Then tell Claude **"I want Bumi live"** and work through
this together.

> **Keys go only in Railway's Variables page. Never paste them into a chat.**
> Swing, Orbi and Uri stay on paper. Only Bumi can use a live account.

## Your checklist

- [ ] **Step 1.** Open and fund an Alpaca live account
- [ ] **Step 2.** Create live API keys
- [ ] **Step 3.** Tell Claude **"Step 2 is done"** (no keys). Claude picks a time outside market hours
- [ ] **Step 4.** Change Bumi's Railway variables
- [ ] **Step 5.** Check the 🔴 LIVE banner
- [ ] **Step 6.** Watch the first real plan, orders and fills with Claude
- [ ] **Step 7.** Raise the size over the following months

---

## Step 1. Open and fund the live account

1. In **app.alpaca.markets**, open a **live** (not paper) brokerage account and finish its approval.
2. Deposit the amount you've decided Bumi can use. Only money you can afford to see drop 20% or more: Bumi's backtest
   already did that once.
3. A regular (cash or margin) account is fine. Bumi holds overnight and never borrows, so the day-trading rule doesn't apply.

## Step 2. Create live API keys

1. Switch to the **live** account in the account switcher and confirm it says live.
2. **API Keys → Generate New Keys**. Copy the key and secret somewhere private.

## Step 3. Tell Claude

Send: **"Step 2 is done"**. Claude confirms the code is current and picks a time outside market hours
(before 9:00 AM or after 4:45 PM ET, and not between Bumi's plan at ~4:30 PM and its orders the next morning).

## Step 4. Change Bumi's Railway variables

Open **Bumi's service → Variables** and set exactly these. Don't change any other service.

```
BUMI_MODE=live
ALPACA_PAPER=false
BUMI_LIVE_CONFIRM=real-money
BUMI_SIZE_FRACTION=0.25
ALPACA_API_KEY=<live key>
ALPACA_SECRET_KEY=<live secret>
```

- All three of `BUMI_MODE`, `ALPACA_PAPER` and `BUMI_LIVE_CONFIRM` must match, or Bumi refuses to start (that's on purpose).
- `BUMI_SIZE_FRACTION=0.25` makes Bumi trade as if it had 25% of the account. With $20k it trades like $5k.
- **Bumi's paper history doesn't carry over.** Claude will help reset Bumi's state file so the live ledger starts clean.

## Step 5. Check the banner

In `#system`, Bumi posts (with a ping):

> 🔴 **Bumi LIVE · REAL MONEY** · account $… · trading as 25% of it ($…)

- **If the account amount is wrong, or it doesn't say LIVE,** stop Bumi's Railway service and tell Claude.
- **If Bumi crashes with "BUMI_MODE=live also needs…",** one of the three settings is off. Fix it and redeploy.

## Step 6. The first real day

- Bumi posts its plan in `#setups` about 30 minutes after the close, marked 🔴 live.
- If it has orders, it sends them at 9:00–9:27 AM ET for the opening auction and confirms fills after 9:35.
- Many days have no trades. Bumi waits in cash until its rules trigger.

## Step 7. Scaling up

Each month, if live results match paper and the backtest, raise `BUMI_SIZE_FRACTION`: 0.25 → 0.5 → 1.0.
Change it outside market hours, then confirm the banner shows the new size.

---

## Safety nets while live

- **Bad day:** down more than 8% in a day on the money Bumi trades (never happened since 2001) → it pauses **new buys**
  and pings you. `/resume-bumi` allows buys again.
- **Drawdown:** down more than 15% from its peak (about once every 5 years in the backtest) → **an alert only; Bumi keeps
  trading.** One alert per slide.
- Bumi never sells because of either; its own exits do the selling.
- **Sanity check:** any plan that would need more money than Bumi has drops its buys and says so in the plan.
- Deposits or withdrawals look like gains or losses to these checks. Tell Claude before moving money.

## Controls (Uri, owner only)

| Command | What it does |
|---|---|
| `/pause-bumi` | No new orders; positions kept. Swing unaffected |
| `/resume-bumi` | Lifts Bumi's pause and any paused buys |
| `/flatten-bumi confirm:yes` | Sells everything in Bumi's account at market, then pauses Bumi |
| `/flatten-all confirm:yes` | Every bot, including Bumi |

You can always close positions yourself in the Alpaca app, but then also `/pause-bumi` so it doesn't buy back.

## Going back to paper

Set `BUMI_MODE=paper`, `ALPACA_PAPER=true`, remove `BUMI_LIVE_CONFIRM`, and put Bumi's **paper** keys back.

This is an implementation checklist, not personal financial advice.
