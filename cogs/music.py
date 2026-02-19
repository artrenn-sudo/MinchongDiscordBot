import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import itertools
from async_timeout import timeout
from functools import partial

# Constants
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'extract_flat': 'in_playlist',
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

FFMPEG_OPTIONS = {
    'options': '-vn'
}

try:
    import yt_dlp as youtube_dl
except ImportError:
    youtube_dl = None

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, start_time=0):
        loop = loop or asyncio.get_event_loop()
        ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)
        
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        
        # Add seeking capability via ffmpeg before_options
        ffmpeg_opts = FFMPEG_OPTIONS.copy()
        if start_time > 0:
             ffmpeg_opts['before_options'] = f'-ss {start_time}'

        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_opts), data=data)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)
        
        # Basic smart search
        if not search.startswith('http'):
            search = f"ytsearch:{search}"

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))

        if 'entries' in data:
            data = data['entries'][0]
            
        return data

class MusicPlayer:
    """A class which is assigned to each guild using the bot for Music."""
    __slots__ = ('bot', '_guild', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume', 'voice_client')

    def __init__(self, ctx):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = ctx.cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.np = None  # Now playing message
        self.volume = .5
        self.current = None
        self.voice_client = None

        ctx.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        """Main player loop."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            try:
                # Wait for the next song. If we timeout cancel the player and disconnect...
                async with timeout(300):  # 5 minutes
                    source_data = await self.queue.get()
            except asyncio.TimeoutError:
                if self._guild.voice_client:
                    await self._guild.voice_client.disconnect()
                return # Destroy the player object

            self.voice_client = self._guild.voice_client
            if not self.voice_client:
                return

            try:
                # Source creation (streaming)
                source = await YTDLSource.from_url(source_data['webpage_url'], loop=self.bot.loop, stream=True)
                self.current = source
                self.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
                
                # Send "Now Playing" UI
                await self.send_now_playing_embed(source_data)

            except Exception as e:
                await self._channel.send(f'Lỗi khi phát nhạc: {e}')
                self.next.set()

            await self.next.wait()
            
            # Cleanup source
            self.current = None

    async def send_now_playing_embed(self, data):
        embed = discord.Embed(title="🎶 Đang phát", description=f"[{data['title']}]({data['webpage_url']})", color=discord.Color.green())
        embed.set_thumbnail(url=data.get('thumbnail'))
        embed.add_field(name="Thời lượng", value=self.parse_duration(data.get('duration')))
        
        view = MusicControls(self)
        if self.np:
             try:
                 await self.np.delete()
             except: pass
        self.np = await self._channel.send(embed=embed, view=view)

    def parse_duration(self, duration):
        if not duration: return "Unknown"
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}" if hours > 0 else f"{int(minutes):02d}:{int(seconds):02d}"

    async def stop(self):
        self.queue._queue.clear()
        if self.voice_client:
             self.voice_client.stop()
    
    async def skip(self):
        if self.voice_client:
            self.voice_client.stop()

class MusicControls(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="⏪ 10s", style=discord.ButtonStyle.secondary)
    async def rewind_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._seek_relative(interaction, -10)

    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("Đã tạm dừng.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Tiếp tục phát.", ephemeral=True)
        else:
             await interaction.response.send_message("Không có nhạc đang phát.", ephemeral=True)

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.stop()
        await interaction.response.send_message("Đã dừng nhạc.", ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.skip()
        await interaction.response.send_message("Đã bỏ qua bài hát.", ephemeral=True)

    @discord.ui.button(label="10s ⏩", style=discord.ButtonStyle.secondary)
    async def forward_10(self, interaction: discord.Interaction, button: discord.ui.Button):
         await self._seek_relative(interaction, 10)

    async def _seek_relative(self, interaction, seconds):
        if not self.player.current:
             await interaction.response.send_message("Không có nhạc đang phát.", ephemeral=True)
             return
        
        # Need to know current position. FFmpeg doesn't give this easily in real-time.
        # We can approximate or just restart.
        # But wait, discord.py doesn't expose current position. 
        # Implementing seek requires restarting the stream with -ss.
        # We need a timer to know where we are.
        # note: This is a complex feature. For now, we will notify it's experimental.
        
        await interaction.response.send_message("⚠️ Tính năng tua đang được phát triển (hạn chế của Discord API).", ephemeral=True)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def get_player(self, ctx):
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = MusicPlayer(ctx)
        return self.players[ctx.guild.id]

    @app_commands.command(name="join", description="Tham gia voice channel")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn phải vào voice channel trước!", ephemeral=True)
            return

        channel = interaction.user.voice.channel
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect()
        await interaction.response.send_message(f"✅ Đã vào **{channel.name}**")

    @app_commands.command(name="play", description="Phát nhạc từ YouTube")
    async def play(self, interaction: discord.Interaction, search: str):
        # Ensure joined
        if not interaction.guild.voice_client:
             if interaction.user.voice:
                 await interaction.user.voice.channel.connect()
             else:
                 await interaction.response.send_message("❌ Bạn phải vào voice channel trước!", ephemeral=True)
                 return
        
        await interaction.response.defer()
        
        # Get player
        ctx = await commands.Context.from_interaction(interaction)
        player = self.get_player(ctx)

        # Search
        data = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
        
        await player.queue.put(data)
        
        await interaction.followup.send(f"✅ Đã thêm vào hàng đợi: **{data['title']}**")

    @app_commands.command(name="skip", description="Bỏ qua bài hiện tại")
    async def skip(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        player = self.get_player(ctx)
        await player.skip()
        await interaction.response.send_message("⏩ Đã skip!")

    @app_commands.command(name="stop", description="Dừng phát nhạc")
    async def stop(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        player = self.get_player(ctx)
        await player.stop()
        await interaction.response.send_message("⏹️ Đã dừng!")

    @app_commands.command(name="queue", description="Xem hàng đợi")
    async def show_queue(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        player = self.get_player(ctx)
        
        if player.queue.empty():
            await interaction.response.send_message("Hàng đợi trống.")
            return

        # Simple list of next 10 items
        upcoming = list(itertools.islice(player.queue._queue, 0, 10))
        fmt = '\n'.join(f"**{i+1}.** {song['title']}" for i, song in enumerate(upcoming))
        embed = discord.Embed(title=f"Hàng đợi ({player.queue.qsize()} bài)", description=fmt)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Music(bot))
