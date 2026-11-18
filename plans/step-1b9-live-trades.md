# Step 1b.9: Live trade management in Discord

Part of [ROADMAP.md](../ROADMAP.md), an addition to [Step 1b](step-1b-paper-orders.md). Status: ✅ Built 2026-11-18 (1b.9.1–1b.9.7) · first live use after deploy

**Goal:** every open paper trade lives as **one card** in `#live-trades`, kept up to date, with buttons to manage it. When it ends, the card moves to `#closed-trades` as a final record.

```
#setups          →  #live-trades            →  #closed-trades
alerts waiting      one card per open           one final card per
for you             position, updated, with     finished trade, and an
                    Close / Break-even /        @mention when it closes
                    Move stop / Move target
```

---

## Decisions (2026-11-18)

| Decision | Choice |
|---|---|
| Channels | New **`#live-trades`** (`DISCORD_CHANNEL_LIVE_TRADES`). **`#trades` is renamed `#closed-trades`** in Discord (same channel ID); its setting is renamed **`DISCORD_CHANNEL_CLOSED_TRADES`** (the old `DISCORD_CHANNEL_TRADES` still works as a fallback) |
| `#setups` after Approve | The alert collapses once the order is placed, with a link to its live card: `-# ⏳ Approved 10:36 AM ET → live card` |
| Card content | Ticker, shares, entry fill and time, **current price**, **unrealized $ and R**, **stop** and **target** with their distance from the price, time left until the 3:55 PM sell, and any changes you made. *No best/worst move.* |
| Updates | About every minute, and right away on events (fill, stop moved, …) |
| Stop changes | **Only upward** (less risk), and below the current price |
| Notifications | Card updates are **silent**; you're **@mentioned only when a trade closes** (in `#closed-trades`) |

---

## The card

**Waiting for the fill** (right after Approve):
```
⏳ [ORB] TSLA · waiting for fill
Limit $366.12 · 6 sh · stop $358.32 · target $380.61 · cancels in 1:20
[ Cancel order ]
```

**In the trade:**
```
🟢 [ORB] TSLA · 6 sh · in since 10:36 AM ET at $365.90
Now $368.40 · +$15.00 · +0.34R
Stop   $358.32  (−2.7% away)
Target $380.61  (+3.3% away)
Sells at 3:55 PM ET (5h 19m)
Changes: stop → break-even $365.90 (10:52 AM)
[ Close now ] [ Break-even ] [ Move stop ] [ Move target ]
```

**The final card in `#closed-trades`** (with an @mention):
```
@you ✅ [ORB] TSLA · target hit · +$87.66 · +1.97R
In $365.90 (10:36 AM) → out $380.61 (1:12 PM) · 6 sh · held 2h 36m
Changes: stop → break-even $365.90 (10:52 AM)
Backtest said: ✅ +2.00R          (added after the 4:15 PM step)
```

## Buttons, and their safety rules

| Button | What it does | Refused when… |
|---|---|---|
| **Cancel order** (waiting) | Cancels the unfilled entry; nothing bought, not counted | already filled |
| **Close now** | Two taps ("Close TSLA? **Confirm**", expires after 30 s) → cancels the stop/target, sells at market, books a **manual** exit | already closed |
| **Break-even** | Moves the stop to your entry fill | the price is at or below your entry (the stop would trigger immediately), or the stop is already there or higher |
| **Move stop** | A small Discord form: type the new stop | it's **lower** than the current stop (stops only move up), or not below the current price |
| **Move target** | A small Discord form: type the new target | it's not above the current price |

- Changes are made **on the bracket at Alpaca** (the stop and target legs are modified in place), so the trade stays protected the whole time
- Every change is **logged** (time, old → new) in a new trade-events record, shown on the card and the final card, and kept for later analysis ("did manual changes help?")
- Only you can press the buttons, as with alerts
- The 3:55 PM sell, the 3:58 backup, `/flatten` and the restart check work as now, and also close/update the cards

---

## Sub-steps

| # | Sub-step | Done when |
|---|---|---|
| 1b.9.1 | **Card model + rendering**: waiting / live / closed card content from the trade log, Alpaca's price and the plan | Card text is tested for each state |
| 1b.9.2 | **Card lifecycle**: posted on Approve (and the `#setups` alert collapses with a link), updated on fill, deleted from `#live-trades` and posted to `#closed-trades` on close, with an @mention. Card message ids saved, so a restart resumes updating them | A paper trade's card goes waiting → live → closed on its own |
| 1b.9.3 | **Minute updates**: price, unrealized $ and R, distances, time left; silent edits | Cards refresh every ~60 s without pinging |
| 1b.9.4 | **Cancel + Close now** (two-tap confirm) | Tested on the real paper account with a test position |
| 1b.9.5 | **Break-even, Move stop, Move target**: Discord forms, the safety rules, changes on Alpaca's bracket legs, logged | Each rule refuses what it should; the change shows at Alpaca and on the card |
| 1b.9.6 | **Rewire existing messages**: fills, stops, targets, the 3:55 sell, `/flatten` and restart results go to the cards (no more event spam); daily summaries unchanged | `#closed-trades` only has final cards |
| 1b.9.7 | **After the close**: the 4:15 PM step adds "Backtest said…" to each closed card | Closed cards show live vs backtest |

## As built (2026-11-18)
- [app/manage.py](../app/manage.py): Cancel, Close now, Break-even, Move stop, Move target with the safety rules; changes on Alpaca's bracket legs (the new leg id is saved so fills still match); every change logged in a new `trade_events` table
- [app/cards.py](../app/cards.py): the waiting / live / closed card text; [app/livecards.py](../app/livecards.py): posting, ~60 s silent refresh, buttons, the price forms, the two-tap Close, moving finished trades to `#closed-trades` (@mention), card ids saved so restarts resume, and "Backtest said…" added after 4:15
- On Approve, the `#setups` alert collapses to `⏳ Approved <time> ET → live card` (a link)
- Fills, stops, targets, the 3:55 sell, `/flatten` and the restart check update the cards instead of posting event messages; summaries of the 3:55 sell go to `#system`
- **Tested on the real paper account** (1-share F position): stop down refused; stop up and target moved at Alpaca with the new leg ids saved; target below the price refused; Close cancelled both legs and sold, leaving nothing open. Plus 12 automated tests
- Without `DISCORD_CHANNEL_LIVE_TRADES`, the app falls back to the old behavior

## Setup (done by you 2026-11-18)
- **You:** rename `#trades` → `#closed-trades`, create **`#live-trades`**, then add `DISCORD_CHANNEL_LIVE_TRADES=<id>` to your local `.env` **and** to Railway's Variables. Suggested notifications: `#live-trades` → Nothing or @mentions only (updates are silent anyway); `#closed-trades` → @mentions.
