# Bumi: your step-by-step

Bumi trades **Defensive + 50% QQQ** on its own $50k Alpaca **paper** account. This is your checklist. Claude handles the code between these steps.

> **Keys and tokens go only in your `.env` or Railway's Variables page. Never paste them into a chat.**

## Where things stand
- [x] **Part 1.** Create the Discord bot
- [x] **Part 2.** Create the Alpaca paper account
- [x] **Part 3.** Bumi's live code deployed
- [x] **Part 4.** Create the Railway service
- [x] **Parts 5 and 6.** Skipped shadow on 2026-11-20 by your choice: Bumi runs with `BUMI_MODE=paper`. For the first two weeks, Claude compares its decisions with a backtest of the same days
- [ ] **Part 7.** Monthly review

---

## Part 1. Create the Discord bot
1. Go to **discord.com/developers/applications** and click **New Application**. Name it **Bumi**.
2. Open **Bot**, click **Reset Token** and copy the token somewhere private for a moment.
3. On the same page, turn **Public Bot** off.
4. Open **OAuth2 → URL Generator**.
   - Scopes: **bot** and **applications.commands**
   - Permissions: **View Channels, Send Messages, Embed Links, Read Message History, Use Slash Commands**
5. Open the generated link and add Bumi to your `claude-trader` server.
6. On your Mac, add this line to `.env`:
   ```
   DISCORD_BOT_TOKEN_BUMI=<Bumi's token>
   ```
7. Keep the token handy for Part 4.

## Part 2. Create the Alpaca paper account
1. Go to **app.alpaca.markets** and open the account switcher at the top left.
2. Click **create a new paper account**. Name it **Bumi** and set the balance to **$50,000**.
3. Switch to the new account. **Check the name before continuing**, so you don't reset or reuse Orbi's keys.
4. Open **API Keys → Generate New Keys** and copy both keys somewhere private for Part 4.

Tell Claude "Parts 1 and 2 are done". Don't send the keys.

## Part 3. Wait for "ready for Railway"
**Do not create the Railway service yet.** Until Bumi's live code is deployed, the app doesn't recognize `STRATEGY=bumi`, so the service would crash and keep retrying.

Claude will tell you once the code is deployed and Orbi, Uri and Brix have been rechecked.

## Part 4. Create the Railway service
Do this **outside market hours** (before 9:30 AM or after 4:15 PM ET).

1. In your Railway project, click **New → GitHub Repo** and choose `claude-trader`.
2. Before it finishes setting up, **attach a volume** mounted at `/data`. Bumi needs its own volume.
3. Open Orbi's service → **Variables → Raw Editor** and copy everything.
4. Open Bumi's service → **Variables → Raw Editor**, paste, then change or add these five lines:
   ```
   STRATEGY=bumi
   BUMI_MODE=shadow
   DISCORD_BOT_TOKEN=<Bumi's Discord token>
   ALPACA_API_KEY=<Bumi's paper key>
   ALPACA_SECRET_KEY=<Bumi's paper secret>
   ```
5. **Double-check before saving:**
   - `STRATEGY` is `bumi`
   - `BUMI_MODE` is `shadow`
   - `ALPACA_PAPER` is `true`
   - The Discord token and both Alpaca keys are **Bumi's, not Orbi's**
   - The channel, server and user ids are unchanged
6. Save and let it deploy.
7. Look in `#system` for Bumi's 🟢 online message, posted under Bumi's name.
8. Confirm Orbi and Uri still show 🟢.

**If anything looks wrong,** open Bumi's service → **Settings** → remove the deployment or stop the service, then tell Claude. Stopping Bumi doesn't affect Orbi or Uri.

## Part 5. Check shadow mode (2 weeks)
Bumi posts what it **would** do each evening and places **no orders**.

Each trading day, check that:
- [ ] Bumi posted a plan after the close
- [ ] The plan shows the VIX level and market state (calm or not)
- [ ] Bumi's Alpaca paper account has **no orders and no positions**
- [ ] Uri shows Bumi as healthy

Quiet days are normal. Bumi averages about 17 dip trades a year.

After 2 weeks, Claude compares Bumi's decisions with a backtest of the same days. **Move on only if they match.**

## Part 6. Turn on paper trading
Only after Claude confirms shadow mode matched.

1. Choose a time outside market hours.
2. In Bumi's Railway Variables, change:
   ```
   BUMI_MODE=paper
   ```
3. Save and let it redeploy.
4. Check `#system` for 🟢 online.
5. The next morning, check that any planned orders appear in Bumi's Alpaca account and fill at the open.

To stop trading at any time, set `BUMI_MODE=shadow` again. Open positions stay open until you close them, or use `/flatten-all` to close positions across **all** bots.

## Part 7. Monthly review
Ask Claude: **"Run Bumi's monthly review."** You should see:

| Check | Healthy | Stop and investigate |
|---|---|---|
| **Orders** | Every planned order was sent and filled | Any missed, duplicate or unplanned order |
| **Positions** | Alpaca matches Bumi's records | Any mismatch |
| **Fill cost** | About 5 bp or less on average | Above 10 bp |
| **Decisions** | Match a backtest of the same days | Any unexplained difference |
| **Uptime** | No missed evening or morning runs | Any missed run |
| **Drawdown** | Under 15% | **15%:** review. **25%:** pause new buys and decide together |

**Timeline**
- **After 1 clean month:** the plumbing is proven. This says little about profit.
- **After 6 months:** first real look at performance against the S&P and QQQ.
- **After 12 months:** decide whether to keep, resize or retire Bumi. It should have seen at least 10 dip trades by then.

Bumi can trail QQQ for long stretches in calm bull markets. That alone isn't a reason to change the rules. **Don't change the rules mid-test**, or the results won't mean anything.

Paper only. Real money remains locked until Step 5 of the roadmap.
