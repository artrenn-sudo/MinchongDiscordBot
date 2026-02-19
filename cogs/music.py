import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os

# Try importing yt_dlp, handle if missing
try:
    import yt_dlp as youtube_dl
except ImportError:
    youtube_dl = None

# YTDL / FFmpeg options
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'extract_flat': 'in_playlist'
}

FFMPEG_OPTIONS = {
    'options': '-vn'
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        if youtube_dl is None:
            raise RuntimeError('`yt_dlp` is required for music playback. Install with `pip install yt-dlp`')
        loop = loop or asyncio.get_event_loop()
        ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)

        if not stream:
             # Basic sanitation if needed, though yt_dlp handles most
             pass

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="join", description="Tham gia voice channel của bạn")
    async def join(self, interaction: discord.Interaction):
        """Joins the voice channel that the user is currently in."""
        
        # Check if the user is in a voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn phải vào một voice channel trước!", ephemeral=True)
            return

        destination_channel = interaction.user.voice.channel
        
        # Check if bot is already in a voice channel
        if interaction.guild.voice_client:
            # Use move_to if already connected
            await interaction.guild.voice_client.move_to(destination_channel)
            await interaction.response.send_message(f"✅ Đã chuyển sang voice channel: **{destination_channel.name}**")
        else:
            # Connect if not connected
            await destination_channel.connect()
            await interaction.response.send_message(f"✅ Đã vào voice channel: **{destination_channel.name}**")

        # Optional: Play join sound if it exists
        await self.play_join_sound(interaction.guild.voice_client)

    @app_commands.command(name="leave", description="Rời khỏi voice channel")
    async def leave(self, interaction: discord.Interaction):
        """Leaves the current voice channel."""
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            await interaction.response.send_message("👋 Đã rời khỏi voice channel.")
        else:
            await interaction.response.send_message("❌ Bot không ở trong voice channel nào.", ephemeral=True)

    async def play_join_sound(self, voice_client):
        """Plays a join sound if available."""
        if voice_client and os.path.exists("join_sound.mp3"):
            try:
                if voice_client.is_playing():
                    voice_client.stop()
                source = discord.FFmpegPCMAudio("join_sound.mp3")
                voice_client.play(source)
            except Exception as e:
                print(f"Error playing join sound: {e}")

async def setup(bot):
    await bot.add_cog(Music(bot))
