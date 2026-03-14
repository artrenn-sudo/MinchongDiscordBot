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
intents.voice_states = True  # Required for DAVE voice encryption

class MinchongBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=["r!", "!"], intents=intents, help_command=commands.DefaultHelpCommand())

    async def setup_hook(self):
        # Explicitly load libopus for Railway/Nixpacks environments
        if not discord.opus.is_loaded():
            try:
                discord.opus.load_opus('libopus.so.0')
            except Exception as e:
                logger.warning(f"Failed to explicitly load libopus: {e}")

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
        
        # Log DAVE/voice dependency info
        try:
            import davey
            logger.info(f'DAVE protocol (davey) version: {davey.__version__}')
        except ImportError:
            logger.warning('davey is NOT installed — DAVE voice encryption will fail!')
        except AttributeError:
            logger.info('davey is installed (no __version__ attribute)')
        
        logger.info(f'discord.py version: {discord.__version__}')
        
        await self.change_presence(
            activity=discord.Streaming(
                name="sanse | choivoigiadinh",
                url="https://www.youtube.com/watch?v=ekr2nIex040"
            )
        )

bot = MinchongBot()

if __name__ == "__main__":
    if not TOKEN:
        logger.critical("Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
