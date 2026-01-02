import discord
import requests
import asyncio
import os

# Tokens & IDs
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN").strip('"')
TORN_API_KEY = os.getenv("TORN_API_KEY")
CHANNEL_ID = 1455264200569131079
FACTION_ID = 52125  # your faction ID

TORN_URL = f"https://api.torn.com/faction/?selections=attacks&key={TORN_API_KEY}"

# Discord client setup
intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

# Keep track of attacks we've already posted
seen_attacks = set()

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

                attacker_link = f"https://www.torn.com/profiles.php?XID={attacker_id}"

                message = (
                    f"🚨 **Faction member attacked!** 🚨\n"
                    f"**Attacker:** {attacker}\n"
                    f"**Defender:** {defender}\n"
                    f"**Respect Lost:** {respect}\n"
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
