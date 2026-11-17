"""python -m app.check: confirms Alpaca (paper) and Discord are wired up. Never prints secrets."""

from __future__ import annotations

import asyncio

import discord
from alpaca.trading.client import TradingClient

from app import settings


def check_alpaca() -> bool:
    print("Alpaca")
    try:
        cfg = settings.alpaca_settings()
        client = TradingClient(cfg.api_key, cfg.secret_key, paper=True)
        account = client.get_account()
        clock = client.get_clock()
    except Exception as e:  # noqa: BLE001 - report any failure in one plain line
        print(f"  FAIL  {type(e).__name__}: {e}")
        return False
    number = str(account.account_number)
    is_paper = number.upper().startswith("PA")
    print(f"  OK    connected to the PAPER endpoint, account …{number[-4:]} "
          f"({'paper' if is_paper else 'CHECK: number does not look like a paper account'})")
    print(f"  OK    status {account.status}, buying power ${float(account.buying_power):,.2f} (fake money)")
    state = "OPEN" if clock.is_open else "CLOSED"
    print(f"  OK    market is {state}. Next open {clock.next_open:%a %Y-%m-%d %H:%M %Z}, "
          f"next close {clock.next_close:%a %Y-%m-%d %H:%M %Z}")
    return is_paper


async def _discord(cfg: settings.DiscordSettings) -> bool:
    ok = True
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        nonlocal ok
        try:
            print(f"  OK    logged in as bot {client.user}")
            guild = client.get_guild(cfg.guild_id)
            if guild is None:
                print("  FAIL  bot is not in the server DISCORD_GUILD_ID (invite it, see setup guide B4)")
                ok = False
                return
            print(f"  OK    in server '{guild.name}'")
            channels = {
                "DISCORD_CHANNEL_SETUPS": cfg.channel_setups,
                "DISCORD_CHANNEL_TRADES": cfg.channel_trades,
                "DISCORD_CHANNEL_DAILY_SUMMARY": cfg.channel_daily_summary,
                "DISCORD_CHANNEL_SYSTEM": cfg.channel_system,
            }
            for name, cid in channels.items():
                ch = guild.get_channel(cid)
                if ch is None:
                    print(f"  FAIL  {name}: channel not found in this server")
                    ok = False
                elif not ch.permissions_for(guild.me).send_messages:
                    print(f"  FAIL  {name}: #{ch.name} found but the bot can't send messages there")
                    ok = False
                else:
                    print(f"  OK    {name}: #{ch.name}")
            owner = guild.get_member(cfg.owner_id) or await guild.fetch_member(cfg.owner_id)
            print(f"  OK    owner (only one allowed to press buttons): {owner.display_name}")
            if ok:
                await guild.get_channel(cfg.channel_system).send(
                    "👋 hello from claude-trader. Connection check passed (Step 1a.2)."
                )
                print("  OK    posted 'hello' in #system")
        except discord.NotFound:
            print("  FAIL  DISCORD_OWNER_ID is not a member of the server")
            ok = False
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {type(e).__name__}: {e}")
            ok = False
        finally:
            await client.close()

    try:
        await client.start(cfg.bot_token)
    except discord.LoginFailure:
        print("  FAIL  DISCORD_BOT_TOKEN was rejected (reset it in the Developer Portal, Bot tab)")
        return False
    return ok


def check_discord() -> bool:
    print("Discord")
    try:
        cfg = settings.discord_settings()
    except settings.SettingsError as e:
        print(f"  FAIL  {e}")
        return False
    return asyncio.run(_discord(cfg))


def check_sec() -> bool:
    print("SEC")
    ok = settings.sec_user_agent() is not None
    print("  OK    SEC_USER_AGENT is set" if ok else "  WARN  SEC_USER_AGENT empty: news will skip 8-K filings")
    return True


def main() -> int:
    settings.load_env()
    results = [check_alpaca(), check_discord(), check_sec()]
    print()
    print("ALL GOOD" if all(results) else "SOMETHING FAILED (see FAIL lines above)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
