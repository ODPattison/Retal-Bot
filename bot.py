import discord
import requests
import asyncio

DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
CHANNEL_ID = 1455264200569131079
TORN_API_KEY = "YOUR_TORN_API_KEY"

TORN_URL = f"https://api.torn.com/faction/?selections=attacks&key={TORN_API_KEY}"

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen_attacks = set()

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(check_attacks())

async def check_attacks():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    # Pre-fill seen_attacks with current attacks so old ones aren't reposted
    response = requests.get(TORN_URL).json()
    attacks = response.get("attacks", {})
    for attack_id in attacks.keys():
        seen_attacks.add(attack_id)

    while not client.is_closed():
        response = requests.get(TORN_URL).json()
        attacks = response.get("attacks", {})

        for attack_id, data in attacks.items():
            if attack_id in seen_attacks:
                continue

            seen_attacks.add(attack_id)

            defender = data["defender_name"]
            attacker = data["attacker_name"]
            attacker_id = data["attacker_id"]

            attacker_link = f"https://www.torn.com/profiles.php?XID={attacker_id}"

            message = (
                f"🚨 **Faction member attacked!** 🚨\n"
                f"**Defender:** {defender}\n"
                f"**Attacker:** {attacker}\n"
                f"🔗 {attacker_link}"
            )

            await channel.send(message)

        await asyncio.sleep(60)

client.run(DISCORD_TOKEN)
