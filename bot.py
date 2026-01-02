import discord
import requests
import asyncio
import os
import time

# ======================
# Tokens & IDs
# ======================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN").strip('"')
TORN_API_KEY = os.getenv("TORN_API_KEY")
FFSCOUTER_KEY = os.getenv("FFSCOUTER_KEY")

CHANNEL_ID = 1456632006602391696
FACTION_ID = 52125

TORN_URL = f"https://api.torn.com/faction/?selections=attacks&key={TORN_API_KEY}"
FFSCOUTER_URL = "https://ffscouter.com/api/v1/get-stats"

# ======================
# Retal window
# ======================
RETAL_WINDOW_SECONDS = 5 * 60

# ======================
# Discord setup
# ======================
intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

# ======================
# State & cache
# ======================
seen_attacks = set()

stat_cache = {}          # {player_id: {"value": "2.99b", "ts": unix}}
CACHE_TTL = 10 * 60      # 10 minutes

# ======================
# Helpers
# ======================
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
    """
    Torn attacks usually include a unix timestamp.
    We try common keys and fall back to 'now' if missing.
    """
    for k in ("timestamp_ended", "timestamp_started", "timestamp"):
        v = data.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return int(time.time())

# ======================
# Bot events
# ======================
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(check_attacks())

# ======================
# Main loop
# ======================
async def check_attacks():
    await client.wait_until_ready()

    channel = client.get_channel(CHANNEL_ID)
    while channel is None:
        print(f"Channel {CHANNEL_ID} not found yet, retrying in 5s...")
        await asyncio.sleep(5)
        channel = client.get_channel(CHANNEL_ID)

    # Pre-fill seen attacks
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

                # Ignore our own faction attacks
                if data.get("attacker_faction") == FACTION_ID:
                    continue

                attacker = data.get("attacker_name", "Someone")
                defender = data.get("defender_name", "Unknown")
                respect = data.get("respect", "Unknown")
                result = data.get("result", "Attacked")

                # Attacker ID can be blank/0 for stealthed attacks
                raw_attacker_id = data.get("attacker_id", 0)
                attacker_id = int(raw_attacker_id) if str(raw_attacker_id).isdigit() else 0

                attacker_link = f"https://www.torn.com/profiles.php?XID={attacker_id}" if attacker_id > 0 else None
                bs_est = get_bs_estimate(attacker_id) if attacker_id > 0 else None

                # Live retal timer using Discord relative timestamps
                attack_ts = get_attack_timestamp(data)
                retal_expires_ts = attack_ts + RETAL_WINDOW_SECONDS

                now_ts = int(time.time())
                delete_in = max(5, retal_expires_ts - now_ts)  # ensure a minimum so it can post

                message = (
                    f"🚨 **Faction Member {result}!** 🚨\n"
                    f"⏳ **Retal ends:** <t:{retal_expires_ts}:R>\n"
                    f"**Attacker:** {attacker}\n"
                    f"**Defender:** {defender}\n"
                    f"**Respect Lost:** {respect}\n"
                    + (f"📊 **Est. Battle Stats:** {bs_est}\n" if bs_est else "")
                    + (f"🔗 {attacker_link}" if attacker_link else "🔗 *(Stealthed attacker — no profile link)*")
                )

                await channel.send(
                    f"@here\n{message}",
                    allowed_mentions=discord.AllowedMentions(everyone=True),
                    delete_after=delete_in
                )

        except Exception as e:
            print(f"Error fetching attacks: {e}")

        await asyncio.sleep(60)

# ======================
# Run
# ======================
client.run(DISCORD_TOKEN)
