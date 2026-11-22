# Swing v1.1: your step-by-step

Swing v1.1 is a **new, separate bot**. It trades QQQ on its own **$100,000 Alpaca paper account**. Swing v1 runs beside it as a model for comparison.

**Bumi, Orbi and Uri stay.** Don't edit, reset or reuse anything that belongs to them.

> **Keys and tokens go only in Railway's Variables page. Never paste them into a chat.**

## Your checklist

- [ ] **Step 1.** Create the Swing Discord bot (5 min)
- [ ] **Step 2.** Create the Swing Alpaca paper account (3 min)
- [ ] **Step 3.** Tell Claude **"Parts 1 and 2 are done"**
- [ ] *Claude pushes the code and checks Orbi, Uri and Bumi*
- [ ] **Step 4.** Create the Swing Railway service (10 min), after Claude says **"ready for Railway"**
- [ ] **Step 5.** Confirm Swing is online
- [ ] **Step 6.** Make sure the fleet isn't paused
- [ ] **Step 7.** Check its first trading day

**To trade Monday:** finish Steps 1–6 before **6:00 AM PT / 9:00 AM ET Monday**.

---

## Step 1. Create the Discord bot

1. Go to **discord.com/developers/applications**.
2. Click **New Application**, name it **Swing**, and create it.
3. Open **Bot** in the left menu.
4. Click **Reset Token**, then copy the token somewhere private. You'll need it in Step 4.
5. On the same page, turn **Public Bot** off and save.
6. Open **OAuth2 → URL Generator**.
7. Under **Scopes**, check:
   - **bot**
   - **applications.commands**
8. Under **Bot Permissions**, check:
   - **View Channels**
   - **Send Messages**
   - **Embed Links**
   - **Read Message History**
   - **Use Slash Commands**
9. Copy the generated URL at the bottom and open it.
10. Add Swing to your **claude-trader** server.

Swing will show as offline until Step 5. That's normal.

## Step 2. Create the Alpaca paper account

1. Go to **app.alpaca.markets**.
2. Open the **account switcher** at the top left.
3. Click **create a new paper account**.
4. Name it **Swing** and set the balance to **$100,000**.
5. Switch into the new account and **confirm the name says Swing**.
6. Open **API Keys → Generate New Keys**.
7. Copy both the **key** and the **secret** somewhere private. You'll need them in Step 4.

**If Alpaca says you've reached its paper account limit, stop and tell Claude.** Don't reset or reuse Bumi's or Orbi's account.

## Step 3. Tell Claude

Send this, without any keys:

> Parts 1 and 2 are done

That is your OK for Claude to commit and push the Swing code. The push briefly restarts Orbi, Uri and Bumi, so Claude will do it outside market hours and confirm all three come back.

**Wait for Claude to say "ready for Railway."** If you create the service earlier, it will crash because the deployed code won't know `STRATEGY=swing` yet.

## Step 4. Create the Railway service

Do this **outside market hours**: before 9:00 AM ET or after 4:15 PM ET.

1. Open your Railway project.
2. Click **New → GitHub Repo** and choose **claude-trader**.
3. Rename the new service **Swing**.
4. Before relying on it, **attach a new volume** to the Swing service, mounted at:
   ```
   /data
   ```
   It must be a **new** volume. Don't attach Bumi's or Orbi's.
5. Open **Orbi's service → Variables → Raw Editor** and copy everything. Don't change anything there.
6. Open **Swing's service → Variables → Raw Editor** and paste.
7. Change or add these five lines:
   ```
   STRATEGY=swing
   SWING_MODE=paper
   DISCORD_BOT_TOKEN=<Swing's Discord token>
   ALPACA_API_KEY=<Swing's paper key>
   ALPACA_SECRET_KEY=<Swing's paper secret>
   ```
8. **Double-check before saving:**
   - [ ] `STRATEGY` is `swing`
   - [ ] `SWING_MODE` is `paper`
   - [ ] `ALPACA_PAPER` is `true`
   - [ ] `BOT_ROLE` is **not** in the list
   - [ ] The Discord token is **Swing's**
   - [ ] Both Alpaca keys are from the **Swing** paper account
   - [ ] The server, owner, channel and database variables are unchanged
9. Save and let it deploy.

## Step 5. Confirm Swing is online

1. In Discord `#system`, look for:
   > 🟢 **Swing v1.1 online** · **paper orders on** · account $100,000
2. Confirm the message is posted by **Swing**.
3. Run `/status` and confirm **Swing, Bumi, Orbi and Uri** all look healthy.
4. Tell Claude **"Swing is online"** so it can review the startup.

**If the account doesn't say $100,000, or it says shadow,** stop the Swing service and tell Claude.

## Step 6. Make sure the fleet isn't paused

A global pause stops Swing from taking new entries.

1. Run `/status`.
2. If it shows a global pause, run `/resume-all`.

This also affects your other bots, so only resume if you want the whole fleet trading.

## Step 7. Check its first trading day

- [ ] Swing is online before **9:00 AM ET**
- [ ] Any trade appears in `#live-trades`
- [ ] Closed trades appear in `#closed-trades`
- [ ] The Swing Alpaca account is **flat after 4:00 PM ET**
- [ ] `#system` posts a summary after **4:05 PM ET** comparing Paper, Model v1.1 and Model v1
- [ ] Bumi, Orbi and Uri behaved normally

Some days have no trade. Its first possible entry is at **10:00 AM ET**. Shortened market days are skipped.

---

## If something goes wrong

- **Close Swing's position:** use `/flatten-all` only if you want **every bot** flattened. For Swing alone, close the QQQ position in Swing's Alpaca paper account, then stop its Railway service.
- **Stop Swing:** open its Railway service and stop or remove the deployment. This doesn't affect Bumi, Orbi or Uri.
- **Anything looks off:** send Claude what you saw. Don't paste keys or tokens.

## What Swing does

- Checks for breakouts every 30 minutes from **10:00 AM to 3:30 PM ET**, long or short.
- Exits when a 15-minute candle closes through the newest FVG, or when a 30-minute check returns inside the band.
- Goes flat by **3:58:45 PM ET** and never holds overnight.
- Uses no resting stop on paper, so results stay comparable to the backtest. Add one before any real money.
