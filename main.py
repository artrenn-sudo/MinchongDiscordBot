import discord
import os
import asyncio
import logging
from discord.ext import commands
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord')

# Load Environment Variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True

class MinchongBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=["r!", "!"], intents=intents, help_command=commands.DefaultHelpCommand())

    async def setup_hook(self):
        # Load extensions/cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and filename != '__init__.py':
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logger.info(f'Loaded extension: {filename}')
                except Exception as e:
                    logger.error(f'Failed to load extension {filename}: {e}')

        # Sync commands
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) globally.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="sanse|choivoigiadinh"
            ),
            status=discord.Status.online
        )

bot = MinchongBot()

if __name__ == "__main__":
    if not TOKEN:
        logger.critical("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
