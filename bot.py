import discord
import requests
import asyncio
import os
import time

# Tokens & IDs
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN").strip('"')
TORN_API_KEY = os.getenv("TORN_API_KEY")
FFSCOUTER_KEY = os.getenv("FFSCOUTER_KEY")  # NEW: set in .env / Railway Variables

CHANNEL_ID = 1456632006602391696
FACTION_ID = 52125  # your faction ID

TORN_URL = f"https://api.torn.com/faction/?selections=attacks&key={TORN_API_KEY}"
FFSCOUTER_URL = "https://ffscouter.com/api/v1/get-stats"  # NEW

# Discord client setup
intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

# Keep track of attacks we've already posted
seen_attacks = set()

# NEW: simple cache to avoid hammering FFScouter
stat_cache = {}     # {player_id: {"value": "2.99b", "ts": unix_time}}
CACHE_TTL = 10 * 60  # 10 mins


def get_bs_estimate(player_id: int):
    """Returns FFScouter bs_estimate_human string (e.g. '2.99b') or None."""
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

        # Expected: list with one dict
        if isinstance(data, list) and data:
            est = data[0].get("bs_estimate_human")
            if est:
                stat_cache[player_id] = {"value": est, "ts": now}
            return est
    except Exception as e:
        print(f"FFScouter lookup failed for {player_id}: {e}")

    return None


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(check_attacks())


async def check_attacks():
    await client.wait_until_ready()

    channel = client.get_channel(CHANNEL_ID)
    while channel is None:
        print(f"Channel {CHANNEL_ID} not found yet, retrying in 5s...")
        await asyncio.sleep(5)
        channel = client.get_channel(CHANNEL_ID)

    # Pre-fill seen_attacks so old attacks aren't reposted
    try:
        response = requests.get(TORN_URL, timeout=10).json()
        attacks = response.get("attacks", {})
        for attack_id in attacks.keys():
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

                attacker_faction = data.get("attacker_faction")

                # Ignore attacks made BY our faction
                if attacker_faction == FACTION_ID:
                    seen_attacks.add(attack_id)
                    continue

                seen_attacks.add(attack_id)

                defender = data.get("defender_name", "Unknown")
                attacker = data.get("attacker_name", "Unknown")
                attacker_id = data.get("attacker_id", 0)
                respect = data.get("respect", "Unknown")

                # pull what happened (Attacked/Hospitalized/Mugged/etc.)
                result = data.get("result", "Attacked")  # safe fallback

                attacker_link = f"https://www.torn.com/profiles.php?XID={attacker_id}"

                # NEW: battle stat estimate (if attacker_id valid + FFSCOUTER_KEY set)
                bs_est = None
                try:
                    if str(attacker_id).isdigit() and int(attacker_id) > 0:
                        bs_est = get_bs_estimate(int(attacker_id))
                except Exception as e:
                    print(f"Error getting bs estimate: {e}")

                message = (
                    f"🚨 **Faction Member {result}!** 🚨\n"
                    f"**Attacker:** {attacker}\n"
                    f"**Defender:** {defender}\n"
                    f"**Respect Lost:** {respect}\n"
                    + (f"📊 **Est. Battle Stats:** {bs_est}\n" if bs_est else "")
                    f"🔗 {attacker_link}"
                )

                await channel.send(
                    f"@here\n{message}",
                    allowed_mentions=discord.AllowedMentions(everyone=True),
                    delete_after=300  # auto-delete after 5 minutes
                )

        except Exception as e:
            print(f"Error fetching attacks: {e}")

        await asyncio.sleep(60)


client.run(DISCORD_TOKEN)
