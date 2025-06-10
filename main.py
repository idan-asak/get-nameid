"""
Discord Member Sync Bot (Render friendly)
========================================

This script runs a Discord bot that synchronises server member data to a
Google Sheet every time the bot starts and whenever someone joins.

Configuration is supplied **only** through environment variables so that
secrets never live in your repo:

- **DISCORD_TOKEN**           – Bot token string
- **DISCORD_GUILD_ID**        – Guild ID to watch (int)
- **SPREADSHEET_ID**          – Google Sheet file ID (the long string in the URL)
- **GOOGLE_CREDENTIALS_JSON** – *base-64* encoded contents of the service-account JSON
- *optional* **SHEET_NAME**    – Worksheet name (default "Discordリスト")
- *optional* **LOG_FILE**      – JSON log file path (default "bot_execution_log.json")

On Render:
  1.  Create a **Background Worker** service.
  2.  Add the above environment variables in the dashboard.  For
      GOOGLE_CREDENTIALS_JSON run `base64 service_account.json` locally
      and paste the output as the value.
  3.  Set *Start Command* to `python main.py` and *Build Command* to
      `pip install -r requirements.txt`.

The free tier will occasionally sleep; the bot writes a line to the log
on each cold-start so you can see how often this happens.
"""

import os
import json
import base64
import tempfile
import asyncio
from datetime import datetime

import discord
from discord.ext import commands

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ──────────────────────────  Config  ──────────────────────────
TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])  # server ID
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = os.getenv("SHEET_NAME", "Discordリスト")
LOG_FILE = os.getenv("LOG_FILE", "bot_execution_log.json")

# ─────────────────  Google credentials bootstrap  ─────────────
json_b64 = os.environ["GOOGLE_CREDENTIALS_JSON"]
json_bytes = base64.b64decode(json_b64)
cred_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
cred_temp.write(json_bytes)
cred_temp.close()

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_name(cred_temp.name, scope)

gs_client = gspread.authorize(creds)
sheet = gs_client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# ───────────────────────  Discord setup  ──────────────────────
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


def write_log(status: str, member_count: int = 0):
    """Append a single entry to the local JSON execution log."""
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "member_count": member_count,
    }
    try:
        data = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, encoding="utf-8") as fp:
                data = json.load(fp)
        data.insert(0, entry)
        # keep last 100 entries
        with open(LOG_FILE, "w", encoding="utf-8") as fp:
            json.dump(data[:100], fp, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[log] failed: {exc}")


async def sync_members():
    """Synchronise all guild members to the Google Sheet."""
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        print("[sync] Guild not found – check DISCORD_GUILD_ID")
        return

    print(f"[sync] fetching members from {guild.name} (ID: {guild.id})")
    existing_ids = set(sheet.col_values(3))  # column C holds Discord user IDs
    added = 0

    for member in guild.members:
        uid = str(member.id)
        if uid in existing_ids:
            continue
        avatar_url = str(member.display_avatar.url)
        sheet.append_row(
            [
                member.display_name,
                member.name,
                uid,
                avatar_url,
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )
        added += 1
        existing_ids.add(uid)
        await asyncio.sleep(1)  # polite API pacing

    print(f"[sync] complete – {added} new rows")
    write_log("sync", added)


# ───────────────────────  Event hooks  ────────────────────────
@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user}")
    await sync_members()


@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id == GUILD_ID:
        await sync_members()


# ────────────────────────────  Run  ───────────────────────────
if __name__ == "__main__":
    write_log("starting")
    bot.run(TOKEN)
