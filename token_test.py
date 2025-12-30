import os
from dotenv import load_dotenv
import discord

load_dotenv()
token = os.getenv("DISCORD_TOKEN")
print(f"Token loaded: {token[:5]}...")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

client.run(token)
