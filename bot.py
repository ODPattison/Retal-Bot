# -*- coding: utf-8 -*-

import discord
import requests
import asyncio
import os
import time
import re
from datetime import datetime, timedelta, timezone

from discord import app_commands
from discord.ext import commands

# ============================================================
# Tempest
# Version: 🔧 v1.6.0
# Change: Slash commands (/quiet) instead of !quiet
# ============================================================

# ============================================================
# CONFIG: Secrets + IDs
# ============================================================
DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip().strip('"')
TORN_API_KEY = os.getenv("TORN_API_KEY")
FFSCOUTER_KEY = os.getenv("FFSCOUTER_KEY")

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
FACTION_ID = int(os.getenv("FACTION_ID", "0"))
ENEMY_FACTION_ID = int(os.getenv("ENEMY_FACTION_ID", "0"))

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN env var")
if CHANNEL_ID == 0:
    raise ValueError("Missing or invalid CHANNEL_ID env var")
if FACTION_ID == 0:
    raise ValueError("Missing or invalid FACTION_ID env var")

# ============================================================
# API Endpoints
# ============================================================
TORN_URL = f"https://api.torn.com/faction/?selections=attacks&key={TORN_API_KEY}"
FFSCOUTER_URL = "https://ffscouter.com/api/v1/get-stats"
ENEMY_TORN_BASIC_URL = "https://api.torn.com/faction/{}"

# ============================================================
# Retal Window
# ============================================================
RETAL_WINDOW_SECONDS = 5 * 60

# ============================================================
# Discord Bot
# ============================================================
intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ============================================================
# Runtime State + Caches
# ============================================================
seen_attacks = set()
QUIET_MODE = False
FLIGHT_TRACKING_PAUSED = False

stat_cache = {}
CACHE_TTL = 10 * 60

# ============================================================
# Helpers
# ============================================================
def get_bs_estimate(player_id: int):
    if not FFSCOUTER_KEY or not player_id:
        return None

    now = int(time.time())
    cached = stat_cache.get(player_id)
    if cached and (now - cached["ts"] < CACHE_TTL):
        return cached["value"]

    try:
        r = requests.get(
            FFSCOUTER_URL,
            params={"key": FFSCOUTER_KEY, "targets": str(player_id)},
            timeout=10
        )
        data = r.json()

        if isinstance(data, list) and data:
            est = data[0].get("bs_estimate_human")
            if est:
                stat_cache[player_id] = {"value": est, "ts": now}
            return est
    except Exception as e:
        print(f"FFScouter lookup failed for {player_id}: {e}")

    return None

def get_attack_timestamp(data: dict) -> int:
    for k in ("timestamp_ended", "timestamp_started", "timestamp"):
        v = data.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return int(time.time())

def format_respect_loss(value):
    if isinstance(value, (int, float)):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, str):
        try:
            f = float(value)
            return f"{f:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return value
    return "Unknown"

# ============================================================
# Enemy travel times table (minutes)
# Standard / Airstrip / Business
# ============================================================
TRAVEL_TIMES_MIN = {
    "Mexico": {"standard": 26, "airstrip": 18, "business": 8},
    "Cayman Islands": {"standard": 35, "airstrip": 25, "business": 11},
    "Canada": {"standard": 41, "airstrip": 29, "business": 12},
    "Hawaii": {"standard": 134, "airstrip": 94, "business": 40},
    "United Kingdom": {"standard": 159, "airstrip": 111, "business": 48},
    "Argentina": {"standard": 167, "airstrip": 117, "business": 50},
    "Switzerland": {"standard": 175, "airstrip": 123, "business": 53},
    "Japan": {"standard": 225, "airstrip": 158, "business": 68},
    "China": {"standard": 242, "airstrip": 169, "business": 72},
    "United Arab Emirates": {"standard": 271, "airstrip": 190, "business": 81},
    "South Africa": {"standard": 297, "airstrip": 208, "business": 89},
}

DEST_ALIASES = {
    "UAE": "United Arab Emirates",
    "United Arab Emirates": "United Arab Emirates",
    "UK": "United Kingdom",
    "United Kingdom": "United Kingdom",
}

def mins_to_pretty(m: int) -> str:
    if m < 60:
        return f"{m}m"
    h = m // 60
    mm = m % 60
    return f"{h}h {mm:02d}m"

def extract_destination(desc: str):
    if not desc:
        return None
    m = re.search(r"(?:Traveling to|Abroad in)\s+(.+)$", desc.strip())
    return m.group(1).strip() if m else None

def extract_return_from(desc: str):
    if not desc:
        return None
    m = re.search(r"(?:Returning to Torn from)\s+(.+)$", desc.strip())
    return m.group(1).strip() if m else None

def normalize_destination(dest):
    if not dest:
        return None
    return DEST_ALIASES.get(dest, dest)

def build_eta(now_utc: datetime, minutes: int) -> str:
    eta = now_utc + timedelta(minutes=minutes)
    return f"{mins_to_pretty(minutes)} (ETA <t:{int(eta.timestamp())}:t>)"

async def send_with_quiet_logic(channel, text: str, delete_after: int):
    global QUIET_MODE
    if QUIET_MODE:
        await channel.send(
            text,
            allowed_mentions=discord.AllowedMentions.none(),
            delete_after=delete_after
        )
    else:
        await channel.send(
            f"@here\n{text}",
            allowed_mentions=discord.AllowedMentions(everyone=True),
            delete_after=delete_after
        )

# ============================================================
# Slash Command: /quiet
# Posts normally + deletes after 5 mins
# ============================================================
DELETE_AFTER = 5 * 60  # 5 minutes

def is_admin(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild

@tree.command(name="quiet", description="Toggle @here pings on/off (admins only).")
@app_commands.describe(mode="on/off/status")
@app_commands.choices(mode=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
    app_commands.Choice(name="status", value="status"),
])
async def quiet(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    global QUIET_MODE

    # Wrong channel
    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(
            f"Hey {interaction.user.mention} you fucking idiot, commands go in <#{CHANNEL_ID}>... MORON 🙄",
            delete_after=DELETE_AFTER
        )
        return

    # Admin check
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if not member or not is_admin(member):
        await interaction.response.send_message(
            "Hmm, I don't think so, only admins can shut me up🤭",
            delete_after=DELETE_AFTER
        )
        return

    choice = mode.value

    if choice == "status":
        await interaction.response.send_message(
            f"🙄Stop asking me things, quiet mode is **{'ON' if QUIET_MODE else 'OFF'}**.",
            delete_after=DELETE_AFTER
        )
        return

    if choice == "on":
        QUIET_MODE = True
        await interaction.response.send_message(
            "😡Fine I'll be quiet. Quiet mode **ON**. No more @here pings.",
            delete_after=DELETE_AFTER
        )
        return

    QUIET_MODE = False
    await interaction.response.send_message(
        "😘Quiet mode **OFF**. @here pings are back 😈",
        delete_after=DELETE_AFTER
    )

# ============================================================
# Slash Command: /flights
# Pause or resume enemy flight tracking
# ============================================================
@tree.command(name="flights", description="Pause or resume enemy flight tracking (admins only).")
@app_commands.describe(mode="pause/resume/status")
@app_commands.choices(mode=[
    app_commands.Choice(name="pause", value="pause"),
    app_commands.Choice(name="resume", value="resume"),
    app_commands.Choice(name="status", value="status"),
])
async def flights(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    global FLIGHT_TRACKING_PAUSED

    if interaction.channel_id != CHANNEL_ID:
        await interaction.response.send_message(
            f"{interaction.user.mention} wrong channel. Behave 😒",
            delete_after=DELETE_AFTER
        )
        return

    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if not member or not is_admin(member):
        await interaction.response.send_message(
            "Nice try. Admins only 🛑",
            delete_after=DELETE_AFTER
        )
        return

    choice = mode.value

    if choice == "status":
        await interaction.response.send_message(
            f"✈️ Flight tracking is **{'PAUSED' if FLIGHT_TRACKING_PAUSED else 'ACTIVE'}**.",
            delete_after=DELETE_AFTER
        )
        return

    if choice == "pause":
        FLIGHT_TRACKING_PAUSED = True
        await interaction.response.send_message(
            "🛑 Flight tracking **PAUSED**. Radar offline.",
            delete_after=DELETE_AFTER
        )
        return

    FLIGHT_TRACKING_PAUSED = False
    await interaction.response.send_message(
        "🟢 Flight tracking **RESUMED**. Eyes back on the skies.",
        delete_after=DELETE_AFTER
    )

# ============================================================
# Enemy Flight Tracking
# ============================================================
enemy_last_state = {}
enemy_last_desc = {}

async def check_enemy_travel():
    await bot.wait_until_ready()

    if ENEMY_FACTION_ID == 0:
        print("ENEMY_FACTION_ID not set, skipping enemy travel tracking.")
        return

    channel = bot.get_channel(CHANNEL_ID)
    while channel is None:
        print(f"Channel {CHANNEL_ID} not found yet, retrying in 5s...")
        await asyncio.sleep(5)
        channel = bot.get_channel(CHANNEL_ID)

    try:
        resp = requests.get(
            ENEMY_TORN_BASIC_URL.format(ENEMY_FACTION_ID),
            params={"selections": "basic", "key": TORN_API_KEY},
            timeout=10
        ).json()

        for uid, m in (resp.get("members") or {}).items():
            st = (m.get("status") or {})
            uid_int = int(uid)
            enemy_last_state[uid_int] = st.get("state") or st.get("status")
            enemy_last_desc[uid_int] = st.get("description", "") or ""
    except Exception as e:
        print(f"Error priming enemy travel cache: {e}")

    while not bot.is_closed():
        if FLIGHT_TRACKING_PAUSED:
            await asyncio.sleep(60)
            continue

        try:
            resp = requests.get(
                ENEMY_TORN_BASIC_URL.format(ENEMY_FACTION_ID),
                params={"selections": "basic", "key": TORN_API_KEY},
                timeout=10
            ).json()

            members = resp.get("members") or {}
            now_utc = datetime.now(timezone.utc)

            for uid_str, m in members.items():
                uid = int(uid_str)
                st = (m.get("status") or {})
                state = st.get("state") or st.get("status")
                desc = st.get("description", "") or ""

                prev_state = enemy_last_state.get(uid)
                prev_desc = enemy_last_desc.get(uid, "")

                enemy_last_state[uid] = state
                enemy_last_desc[uid] = desc

                raw_name = m.get("name", f"User {uid}")
                profile_link = f"https://www.torn.com/profiles.php?XID={uid}"
                name = f"[{raw_name}]({profile_link})"

                bs_est = get_bs_estimate(uid)
                bs_line = f"📊 **Est. Battle Stats:** {bs_est}\n" if bs_est else ""

                if prev_desc.startswith("In ") and desc.startswith("Returning to Torn from"):
                    from_place = normalize_destination(extract_return_from(desc)) or "Unknown"
                    times = TRAVEL_TIMES_MIN.get(from_place)

                    if not times:
                        msg = (
                            f"🛬 **{name}** — Returning from **{from_place}**\n"
                            + bs_line
                            + "_(No travel time data for this destination yet)_"
                        )
                        await send_with_quiet_logic(channel, msg, delete_after=6 * 60 * 60)
                        continue

                    msg = (
                        f"🛬 **{name}** — Returning from **{from_place}**\n"
                        + bs_line
                        + f"Standard: {build_eta(now_utc, times['standard'])}\n"
                        + f"Airstrip: {build_eta(now_utc, times['airstrip'])}\n"
                        + f"Business: {build_eta(now_utc, times['business'])}\n"
                    )
                    delete_after = (times["standard"] * 60) + 120
                    await send_with_quiet_logic(channel, msg, delete_after=delete_after)
                    continue

                if prev_state in (None, "Okay", "Ok") and state == "Traveling":
                    dest = normalize_destination(extract_destination(desc)) or "Unknown"
                    times = TRAVEL_TIMES_MIN.get(dest)

                    if not times:
                        msg = (
                            f"🛫 **{name}** — Travelling to **{dest}**\n"
                            + bs_line
                            + "_(No travel time data for this destination yet)_"
                        )
                        await send_with_quiet_logic(channel, msg, delete_after=6 * 60 * 60)
                        continue

                    msg = (
                        f"🛫 **{name}** — Travelling to **{dest}**\n"
                        + bs_line
                        + f"Standard: {build_eta(now_utc, times['standard'])}\n"
                        + f"Airstrip: {build_eta(now_utc, times['airstrip'])}\n"
                        + f"Business: {build_eta(now_utc, times['business'])}\n"
                    )
                    delete_after = (times["standard"] * 60) + 120
                    await send_with_quiet_logic(channel, msg, delete_after=delete_after)

        except Exception as e:
            print(f"Error fetching enemy travel: {e}")

        await asyncio.sleep(60)

# ============================================================
# Retal Polling
# ============================================================
async def check_attacks():
    await bot.wait_until_ready()

    channel = bot.get_channel(CHANNEL_ID)
    while channel is None:
        print(f"Channel {CHANNEL_ID} not found yet, retrying in 5s...")
        await asyncio.sleep(5)
        channel = bot.get_channel(CHANNEL_ID)

    try:
        response = requests.get(TORN_URL, timeout=10).json()
        for attack_id in response.get("attacks", {}).keys():
            seen_attacks.add(str(attack_id))
    except Exception as e:
        print(f"Error fetching initial attacks: {e}")

    while not bot.is_closed():
        try:
            response = requests.get(TORN_URL, timeout=10).json()
            attacks = response.get("attacks", {})

            for attack_id, data in attacks.items():
                attack_id = str(attack_id)
                if attack_id in seen_attacks:
                    continue
                seen_attacks.add(attack_id)

                if data.get("attacker_faction") == FACTION_ID:
                    continue

                attacker = data.get("attacker_name", "Someone")
                defender = data.get("defender_name", "Unknown")

                respect_loss_raw = data.get("respect_loss", None)
                respect_loss = format_respect_loss(respect_loss_raw)

                result = data.get("result", "Attacked")
                result_norm = str(result).strip().lower()
                if result_norm in ("lost", "stalemate", "interrupted"):
                    continue

                raw_attacker_id = data.get("attacker_id", 0)
                attacker_id = int(raw_attacker_id) if str(raw_attacker_id).isdigit() else 0

                attacker_md = attacker
                if attacker_id > 0:
                    attacker_profile = f"https://www.torn.com/profiles.php?XID={attacker_id}"
                    attacker_md = f"[{attacker}]({attacker_profile})"

                bs_est = get_bs_estimate(attacker_id) if attacker_id > 0 else None

                attack_ts = get_attack_timestamp(data)
                retal_expires_ts = attack_ts + RETAL_WINDOW_SECONDS

                now_ts = int(time.time())
                delete_in = max(5, retal_expires_ts - now_ts)

                message = (
                    f"🚨 **Faction Member {result}!** 🚨\n"
                    f"⏳ **Retal ends:** <t:{retal_expires_ts}:R>\n"
                    f"**Attacker:** {attacker_md}\n"
                    f"**Defender:** {defender}\n"
                    f"**Respect Lost:** {respect_loss}\n"
                    + (f"📊 **Est. Battle Stats:** {bs_est}\n" if bs_est else "")
                )

                if QUIET_MODE:
                    await channel.send(
                        message,
                        allowed_mentions=discord.AllowedMentions.none(),
                        delete_after=delete_in
                    )
                else:
                    await channel.send(
                        f"@here\n{message}",
                        allowed_mentions=discord.AllowedMentions(everyone=True),
                        delete_after=delete_in
                    )

        except Exception as e:
            print(f"Error fetching attacks: {e}")

        await asyncio.sleep(60)

# ============================================================
# Bot Startup
# ============================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Command sync failed: {e}")

    bot.loop.create_task(check_attacks())
    bot.loop.create_task(check_enemy_travel())

# ============================================================
# Run the bot
# ============================================================
bot.run(DISCORD_TOKEN)
