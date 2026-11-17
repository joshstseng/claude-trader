# Setup: Alpaca paper account + Discord bot (Step 1a.2)

About 20–25 minutes. You'll end with values to paste into a `.env` file at the repo root.

> **Never paste keys or tokens into a chat** (Claude, Discord or anywhere else). They only go in `.env`, which git ignores.

First create your `.env`: copy `.env.example` to `.env` at the repo root (`cp .env.example .env`), then fill it in as you go.

---

## Part A: Alpaca (paper trading), ~5 min

1. Go to **https://alpaca.markets** and click **Sign Up**. An email and password is enough. **For paper trading you don't need to fund anything or finish the brokerage application.** If it asks, choose the individual account. You can skip identity steps that are only needed for live trading.
2. Log in to the dashboard at **https://app.alpaca.markets**.
3. Top left, use the account switcher to pick your **Paper** account (it usually starts with `PA…`). Make sure it says Paper, not Live.
4. On the Paper home page, find **API Keys** (right side) and click **Generate New Keys** (or **Regenerate**).
5. You'll see an **API Key ID** and a **Secret Key**. **The secret is shown only once**, so copy both into `.env` right away:
   ```
   ALPACA_API_KEY=PK...
   ALPACA_SECRET_KEY=...
   ALPACA_PAPER=true
   ```
6. Leave `ALPACA_PAPER=true`. The app refuses to start if it's anything else.

Paper accounts start with $100,000 of fake money. That doesn't matter: the ORB bot sizes trades from our own $5,000 setting.

---

## Part B: Discord, ~15 min

### B1. Turn on Developer Mode (to copy IDs)
1. Discord app → **User Settings** (gear icon) → **Advanced** → turn on **Developer Mode**.
2. Now right-clicking a server, channel or user shows **Copy … ID**.

### B2. Create the private server
1. In the left sidebar click **+** → **Create My Own** → **For me and my friends**. Name it e.g. `claude-trader`.
2. Create 4 text channels (click **+** next to "Text Channels"):
   - `setups`
   - `trades`
   - `daily-summary`
   - `system`
3. Right-click the server icon → **Copy Server ID**, then paste it in `.env`:
   ```
   DISCORD_GUILD_ID=...
   ```
4. For each channel, right-click → **Copy Channel ID** and paste:
   ```
   DISCORD_CHANNEL_SETUPS=...
   DISCORD_CHANNEL_TRADES=...
   DISCORD_CHANNEL_DAILY_SUMMARY=...
   DISCORD_CHANNEL_SYSTEM=...
   ```
5. Right-click **your own name** (in a member list or on a message) → **Copy User ID**:
   ```
   DISCORD_OWNER_ID=...
   ```
   Only this user will be allowed to press buttons and use commands.

### B3. Create the bot
1. Go to **https://discord.com/developers/applications** → **New Application** → name it e.g. `ORB Bot` → Create.
2. Left menu → **Bot**:
   - Click **Reset Token** → copy the token into `.env`:
     ```
     DISCORD_BOT_TOKEN=...
     ```
   - Turn **off** "Public Bot", so only you can add it to servers.
   - Leave the three "Privileged Gateway Intents" **off**. We don't need them.
3. Left menu → **Installation**: if there's an "Install Link" setting, set it to **None** (otherwise "Public Bot" can't be turned off).

### B4. Invite the bot to your server
1. Left menu → **OAuth2** → **URL Generator**.
2. Scopes: tick **bot** and **applications.commands**.
3. Bot permissions: tick **View Channels**, **Send Messages**, **Embed Links**, **Read Message History**, **Use Slash Commands**.
4. Copy the generated URL at the bottom, open it in your browser, pick your `claude-trader` server, and click **Authorize**.
5. The bot appears in the member list as offline. That's expected: it comes online when our app runs.

### B5. Phone notifications
1. Install Discord on your phone and log in.
2. For `#setups` and `#trades`: long-press the channel → **Notification Settings** → **All Messages**.
3. `#daily-summary` and `#system`: your choice. I'd use **Only @mentions** for `#system`; the bot will @mention you on real errors.

---

## Part C: SEC user agent (for 8-K filings in news), ~1 min

The SEC asks automated tools to identify themselves. In `.env`:
```
SEC_USER_AGENT=Your Name your-email@example.com
```
Use your own name and email. It's only sent to sec.gov.

---

## Done?

When `.env` is filled in, tell Claude **"setup done"**. Claude will run `python -m app.check`, which:
- Prints Alpaca's market clock (and confirms it's the paper account)
- Posts "hello" in `#system`

Values won't be shown back in chat.
