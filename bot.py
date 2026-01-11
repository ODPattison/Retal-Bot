import discord
import requests
import asyncio
import os
import time

# ============================================================
# Retal Bot
# Version: 🔧 v1.4.4
# Change: Added wrong-channel warning for !quiet commands (with cooldown)
# ============================================================

# ============================================================
# CONFIG: Secrets + IDs
# ============================================================
DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip().strip('"')
TORN_API_KEY = os.getenv("TORN_API_KEY")
FFSCOUTER_KEY = os.getenv("FFSCOUTER_KEY")

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
FACTION_ID = int(os.getenv("FACTION_ID", "0"))

# Optional: crash early if config missing (recommended)
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

# ============================================================
# Retal Window
# ============================================================
RETAL_WINDOW_SECONDS = 5 * 60

# ============================================================
# Command cleanup window (delete command + response)
# ============================================================
COMMAND_CLEANUP_SECONDS = 5 * 60  # 5 minutes

# ============================================================
# Wrong channel command warning (anti spam)
# ============================================================
WRONG_CHANNEL_COOLDOWN = 30  # seconds
last_wrong_channel_notice = {}  # {(channel_id, user_id): ts}

# ============================================================
# Discord Client
# - We need message_content to read commands like !quiet on/off
# ============================================================
intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True  # IMPORTANT for reading chat commands
client = discord.Client(intents=intents)

# ============================================================
# Runtime State
# ============================================================
seen_attacks = set()

# Quiet mode (in-memory)
QUIET_MODE = False

# ============================================================
# FFScouter Cache
# ============================================================
stat_cache = {}          # {player_id: {"value": "2.99b", "ts": unix}}
CACHE_TTL = 10 * 60      # 10 minutes

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
    """
    Torn's respect_loss is usually a float.
    We format to 2dp, then strip trailing zeros/dot so it looks clean.
    """
    if isinstance(value, (int, float)):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, str):
        # best effort for stringy numbers
        try:
            f = float(value)
            return f"{f:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return value
    return "Unknown"

# ============================================================
# Discord command handler
# Commands:
#   !quiet on
#   !quiet off
#   !quiet status
# (restricted to admins / manage_guild)
# Deletes BOTH the command message + bot response after 5 mins
# ============================================================
@client.event
async def on_message(message: discord.Message):
    global QUIET_MODE

    # ignore bots (including ourselves)
    if message.author.bot:
        return

    content_raw = (message.content or "").strip()
    content = content_raw.lower()

    # Only treat !quiet as a command (ignore everything else)
    is_quiet_command = content.startswith("!quiet")

    # If someone tries !quiet in the wrong channel, warn them in that channel
    if is_quiet_command and message.channel.id != CHANNEL_ID:
        now = int(time.time())
        key = (message.channel.id, message.author.id)
        last = last_wrong_channel_notice.get(key, 0)

        if now - last >= WRONG_CHANNEL_COOLDOWN:
            last_wrong_channel_notice[key] = now
            await message.channel.send(
                f"Hey {message.author.mention} you fucking idiot, commands go in <#{CHANNEL_ID}>... MORON 🙄",
                delete_after=20
            )
        return

    # Keep actual command handling scoped to your channel
    if message.channel.id != CHANNEL_ID:
        return

    if not is_quiet_command:
        return

    # schedule deletion of the user's command after 5 mins (best effort)
    async def delete_command_later(msg: discord.Message):
        await asyncio.sleep(COMMAND_CLEANUP_SECONDS)
        try:
            await msg.delete()
        except Exception:
            pass

    client.loop.create_task(delete_command_later(message))

    # permission check: admin or manage_guild
    perms = getattr(message.author, "guild_permissions", None)
    if not perms or not (perms.administrator or perms.manage_guild):
        await message.channel.send(
            "Hmm, I don't think so, only admins can shut me up🤭",
            delete_after=COMMAND_CLEANUP_SECONDS
        )
        return

    parts = content.split()
    if len(parts) == 1 or parts[1] == "status":
        await message.channel.send(
            f"🙄Stop asking me things, quiet mode is **{'ON' if QUIET_MODE else 'OFF'}**.",
            delete_after=COMMAND_CLEANUP_SECONDS
        )
        return

    if parts[1] in ("on", "true", "1", "enable", "enabled"):
        QUIET_MODE = True
        await message.channel.send(
            "😡Fine I'll be quiet. Quiet mode **ON** — no more `@here` pings. Dick",
            delete_after=COMMAND_CLEANUP_SECONDS
        )
        return

    if parts[1] in ("off", "false", "0", "disable", "disabled"):
        QUIET_MODE = False
        await message.channel.send(
            "😘Awh you missed me. Quiet mode **OFF** — `@here` pings are back. ^.^ ",
            delete_after=COMMAND_CLEANUP_SECONDS
        )
        return

    await message.channel.send(
        "Usage: `!quiet on`, `!quiet off`, or `!quiet status`",
        delete_after=COMMAND_CLEANUP_SECONDS
    )

# ============================================================
# Bot Startup
# ============================================================
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(check_attacks())

# ============================================================
# Main Polling Loop
# ============================================================
async def check_attacks():
    global QUIET_MODE
    await client.wait_until_ready()

    channel = client.get_channel(CHANNEL_ID)
    while channel is None:
        print(f"Channel {CHANNEL_ID} not found yet, retrying in 5s...")
        await asyncio.sleep(5)
        channel = client.get_channel(CHANNEL_ID)

    # On boot: mark current attacks as "already seen"
    try:
        response = requests.get(TORN_URL, timeout=10).json()
        for attack_id in response.get("attacks", {}).keys():
            seen_attacks.add(str(attack_id))
    except Exception as e:
        print(f"Error fetching initial attacks: {e}")

    while not client.is_closed():
        try:
            response = requests.get(TORN_URL, timeout=10).json()
            attacks = response.get("attacks", {})

            for attack_id, data in attacks.items():
                attack_id = str(attack_id)
                if attack_id in seen_attacks:
                    continue
                seen_attacks.add(attack_id)

                # Ignore attacks launched by our own faction
                if data.get("attacker_faction") == FACTION_ID:
                    continue

                attacker = data.get("attacker_name", "Someone")
                defender = data.get("defender_name", "Unknown")

                # ✅ FIX: respect loss is in respect_loss
                respect_loss_raw = data.get("respect_loss", None)
                respect_loss = format_respect_loss(respect_loss_raw)

                result = data.get("result", "Attacked")

                # Ignore non-retalable outcomes
                result_norm = str(result).strip().lower()
                if result_norm in ("lost", "stalemate", "interrupted"):
                    continue

                raw_attacker_id = data.get("attacker_id", 0)
                attacker_id = int(raw_attacker_id) if str(raw_attacker_id).isdigit() else 0

                attacker_link = f"https://www.torn.com/profiles.php?XID={attacker_id}" if attacker_id > 0 else None
                bs_est = get_bs_estimate(attacker_id) if attacker_id > 0 else None

                attack_ts = get_attack_timestamp(data)
                retal_expires_ts = attack_ts + RETAL_WINDOW_SECONDS

                now_ts = int(time.time())
                delete_in = max(5, retal_expires_ts - now_ts)

                message = (
                    f"🚨 **Faction Member {result}!** 🚨\n"
                    f"⏳ **Retal ends:** <t:{retal_expires_ts}:R>\n"
                    f"**Attacker:** {attacker}\n"
                    f"**Defender:** {defender}\n"
                    f"**Respect Lost:** {respect_loss}\n"
                    + (f"📊 **Est. Battle Stats:** {bs_est}\n" if bs_est else "")
                    + (f"🔗 {attacker_link}" if attacker_link else "🔗 *(Stealthed attacker — no profile link)*")
                )

                # QUIET MODE: no @here, and block mention pings completely
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
# Run the bot
# ============================================================
client.run(DISCORD_TOKEN)
