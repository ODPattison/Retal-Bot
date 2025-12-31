import discord
import requests
import asyncio
import os

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN").strip('"')
TORN_API_KEY = os.getenv("TORN_API_KEY")
CHANNEL_ID = 1455264200569131079

TORN_URL = f"https://api.torn.com/faction/?selections=attacks&key={TORN_API_KEY}"

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True  # ensure the bot can send messages
client = discord.Client(intents=intents)

seen_attacks = set()

async def check_attacks():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while channel is None:
        await asyncio.sleep(5)
        channel = client.get_channel(CHANNEL_ID)

    # Prefill seen_attacks
    try:
        response = requests.get(TORN_URL, timeout=10).json()
        attacks = response.get("attacks", {})
        for attack_id in attacks.keys():
            seen_attacks.add(str(attack_id))
    except Exception as e:
        print(f"Error fetching initial attacks: {e}")

    while True:
        try:
            response = requests.get(TORN_URL, timeout=10).json()
            attacks = response.get("attacks", {})

            for attack_id, data in attacks.items():
                attack_id = str(attack_id)
                if attack_id in seen_attacks:
                    continue

                respect_text = str(data.get("respect_gain") or data.get("respect") or "")
                if "-" not in respect_text:  # only show negative respect attacks
                    continue

                seen_attacks.add(attack_id)

                defender = data.get("defender_name", "Unknown")
                attacker = data.get("attacker_name", "Unknown")
                attacker_id = data.get("attacker_id", 0)
                attacker_link = f"https://www.torn.com/profiles.php?XID={attacker_id}"

                message = (
                    f"🚨 **Faction member attacked!** 🚨\n"
                    f"**Attacker:** {attacker}\n"
                    f"**Defender:** {defender}\n"
                    f"**Respect lost:** {respect_text}\n"
                    f"🔗 {attacker_link}"
                )

                await channel.send(f"@here\n{message}", allowed_mentions=discord.AllowedMentions(everyone=True))
        except Exception as e:
            print(f"Error fetching attacks: {e}")

        await asyncio.sleep(60)

# ✅ Safe background task startup for Discord.py v2.x
@client.event
async def setup_hook():
    asyncio.create_task(check_attacks())

client.run(DISCORD_TOKEN)
