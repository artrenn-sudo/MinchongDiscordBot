import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import itertools
import time
from async_timeout import timeout
import os

# Constants
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'extract_flat': 'in_playlist',
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    # Optimizations
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'no_warnings': True,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -bufsize 8192k'
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
        
        # Check for local ffmpeg
        executable = 'ffmpeg'
        if os.path.isfile('ffmpeg.exe'):
            executable = './ffmpeg.exe'
        elif os.path.isfile('bin/ffmpeg.exe'):
             executable = 'bin/ffmpeg.exe'

        # Merge options
        ffmpeg_opts = FFMPEG_OPTIONS.copy()
        if start_time > 0:
             # Add seeking to before_options
             current_before = ffmpeg_opts.get('before_options', '')
             ffmpeg_opts['before_options'] = f'{current_before} -ss {start_time}'

        return cls(discord.FFmpegPCMAudio(filename, executable=executable, **ffmpeg_opts), data=data)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)
        
        if not search.startswith('http'):
            search = f"ytsearch:{search}"

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))

        if 'entries' in data:
            data = data['entries'][0]
            
        return data

class MusicPlayer:
    __slots__ = ('bot', '_guild', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume', 'voice_client', 
                 'start_time', 'pause_start', 'pause_duration', 'seeking', 'current_data', 'seek_position', 'loop_mode')

    def __init__(self, ctx, cog):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.np = None 
        self.volume = .5
        self.current = None
        self.voice_client = None
        
        self.start_time = 0
        self.pause_start = 0
        self.pause_duration = 0
        
        self.seeking = False
        self.current_data = None
        self.seek_position = 0
        
        # 0: Off, 1: Song, 2: Queue
        self.loop_mode = 0

        ctx.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            try:
                # Loop Queue Logic: Re-add current song if needed
                if self.loop_mode == 2 and self.current_data and not self.seeking:
                     await self.queue.put(self.current_data)

                # Loop Song Logic: Reuse current data
                if self.loop_mode == 1 and self.current_data and not self.seeking:
                     source_data = self.current_data
                     self.seek_position = 0
                elif not self.seeking:
                    async with timeout(300): # 5 min timeout
                        source_data = await self.queue.get()
                        self.current_data = source_data
                        self.seek_position = 0
                else:
                    # Seeking
                    source_data = self.current_data
                    self.seeking = False
            
            except asyncio.TimeoutError:
                if self._guild.voice_client:
                    await self._guild.voice_client.disconnect()
                return

            self.voice_client = self._guild.voice_client
            if not self.voice_client:
                return

            try:
                source = await YTDLSource.from_url(source_data['webpage_url'], loop=self.bot.loop, stream=True, start_time=self.seek_position)
                self.current = source
                
                self.start_time = time.time() - self.seek_position
                self.pause_duration = 0
                self.pause_start = 0
                
                self.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
                await self.send_now_playing_embed(source_data)

            except Exception as e:
                await self._channel.send(f'⚠️ Lỗi phát nhạc: {e}')
                self.next.set()

            await self.next.wait()
            self.current = None

    def get_current_position(self):
        if not self.current or not self.start_time: return 0
        current_pause = 0
        if self.pause_start > 0: current_pause = time.time() - self.pause_start
        return max(0, time.time() - self.start_time - self.pause_duration - current_pause)

    async def seek(self, seconds):
        if not self.voice_client or not self.current: return
        if seconds < 0: seconds = 0
        if self.current.duration and seconds > self.current.duration: seconds = self.current.duration - 1
        
        self.seeking = True
        self.seek_position = seconds
        self.voice_client.stop()

    async def stop(self):
        self.queue = asyncio.Queue()
        self.seeking = False
        self.loop_mode = 0
        if self.voice_client: self.voice_client.stop()
    
    async def skip(self):
        self.seeking = False
        # If loop song is on, force skip prevents replaying same song
        forced_loop_reset = False
        if self.loop_mode == 1:
            self.loop_mode = 0
            forced_loop_reset = True
            
        if self.voice_client: self.voice_client.stop()
        
        # Restore loop mode if needed? usually skip means "Next please", so breaking loop song is expected.
        # But user might want to keep loop song ON for the NEXT song?
        # For now, let's disable loop song on skip to avoid confusion.
        if forced_loop_reset:
             # Identify if we should restore? No, standard behavior is usually "Skip current" -> Play next.
             # If "Loop Song" was on, it applies to the CURRENT song. So skipping it implies we are done with it.
             # Does it apply to the next song? "Repeat One". Yes.
             # So we should restore it.
             # But my logic in player_loop checks `self.loop_mode == 1` to replay `self.current_data`.
             # So I need to change `self.current_data`?
             self.current_data = None # This forces player_loop to get from queue
             self.loop_mode = 1 # Restore mode

    def parse_duration(self, duration):
        if not duration: return "--:--"
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}" if hours > 0 else f"{int(minutes):02d}:{int(seconds):02d}"

    async def send_now_playing_embed(self, data):
        embed = discord.Embed(title="🎶 Đang phát", description=f"[{data['title']}]({data['webpage_url']})", color=discord.Color.brand_green())
        embed.set_thumbnail(url=data.get('thumbnail'))
        embed.add_field(name="Thời lượng", value=self.parse_duration(data.get('duration')), inline=True)
        
        status = []
        if self.loop_mode == 1: status.append("🔂 Lặp bài")
        if self.loop_mode == 2: status.append("🔁 Lặp bài")
        if status: embed.set_footer(text=" | ".join(status))

        view = MusicControls(self)
        if self.np:
             try: await self.np.delete()
             except: pass
        self.np = await self._channel.send(embed=embed, view=view)

class MusicControls(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="⏪ 10s", style=discord.ButtonStyle.secondary)
    async def rewind(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._seek_relative(interaction, -10)

    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.primary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            self.player.pause_start = time.time()
            await interaction.response.send_message("⏸️ Tạm dừng", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            if self.player.pause_start > 0:
                self.player.pause_duration += (time.time() - self.player.pause_start)
                self.player.pause_start = 0
            await interaction.response.send_message("▶️ Tiếp tục", ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.skip()
        await interaction.response.send_message("⏩ Skip", ephemeral=True)
        
    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.stop()
        await interaction.response.send_message("⏹️ Stop", ephemeral=True)

    @discord.ui.button(label="10s ⏩", style=discord.ButtonStyle.secondary)
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._seek_relative(interaction, 10)

    async def _seek_relative(self, interaction, seconds):
        if not self.player.current: return
        pos = self.player.get_current_position()
        await self.player.seek(pos + seconds)
        await interaction.response.send_message(f"Seeking to {int(pos+seconds)}s", ephemeral=True)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def get_player(self, ctx):
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = MusicPlayer(ctx, self)
        return self.players[ctx.guild.id]

    @app_commands.command(name="join")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
             return await interaction.response.send_message("❌ Vào voice trước!", ephemeral=True)
        channel = interaction.user.voice.channel
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect()
        await interaction.response.send_message(f"✅ Joined {channel.name}")

    @app_commands.command(name="leave")
    async def leave(self, interaction: discord.Interaction):
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
            if interaction.guild.id in self.players:
                del self.players[interaction.guild.id]
            await interaction.response.send_message("👋 Bye!")
        else:
            await interaction.response.send_message("❌ Không ở trong voice.")

    @app_commands.command(name="play")
    async def play(self, interaction: discord.Interaction, search: str):
        if not interaction.guild.voice_client:
            if interaction.user.voice:
                await interaction.user.voice.channel.connect()
            else:
                return await interaction.response.send_message("❌ Vào voice trước!", ephemeral=True)
        
        await interaction.response.defer()
        player = self.get_player(await commands.Context.from_interaction(interaction))
        
        try:
            data = await YTDLSource.create_source(player, search, loop=self.bot.loop)
            await player.queue.put(data)
            await interaction.followup.send(f"✅ Added: **{data['title']}**")
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    @app_commands.command(name="loop")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value=0),
        app_commands.Choice(name="Song", value=1),
        app_commands.Choice(name="Queue", value=2)
    ])
    async def loop_cmd(self, interaction: discord.Interaction, mode: int):
        player = self.get_player(await commands.Context.from_interaction(interaction))
        player.loop_mode = mode
        modes = ["Off", "Song", "Queue"]
        await interaction.response.send_message(f"🔁 Loop mode: **{modes[mode]}**")

    @app_commands.command(name="queue")
    async def queue_cmd(self, interaction: discord.Interaction):
        player = self.get_player(await commands.Context.from_interaction(interaction))
        if player.queue.empty():
            return await interaction.response.send_message("📭 Hàng đợi trống.")
        
        upcoming = list(itertools.islice(player.queue._queue, 0, 10))
        desc = ""
        for i, song in enumerate(upcoming):
            desc += f"**{i+1}.** {song['title']}\n"
        
        embed = discord.Embed(title=f"Queue ({player.queue.qsize()})", description=desc)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear_queue", description="Xóa toàn bộ hàng đợi nhạc")
    async def clear_queue(self, interaction: discord.Interaction):
        player = self.get_player(await commands.Context.from_interaction(interaction))
        player.queue = asyncio.Queue()
        player.loop_mode = 0 # Reset loop too
        await interaction.response.send_message("🗑️ Đã xóa hàng đợi.")

    @app_commands.command(name="skip")
    async def skip(self, interaction: discord.Interaction):
        player = self.get_player(await commands.Context.from_interaction(interaction))
        await player.skip()
        await interaction.response.send_message("⏩ Skipped.")

    @app_commands.command(name="stop")
    async def stop(self, interaction: discord.Interaction):
        player = self.get_player(await commands.Context.from_interaction(interaction))
        await player.stop()
        await interaction.response.send_message("⏹️ Stopped.")

async def setup(bot):
    await bot.add_cog(Music(bot))
