import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import itertools
import time
import logging
import os

try:
    from async_timeout import timeout
except ImportError:
    # Python 3.11+ has asyncio.timeout built-in
    from asyncio import timeout

logger = logging.getLogger(__name__)

# Constants — Cookie file detection
def _get_cookie_file():
    for name in ('cookies.txt', 'youtube-cookies.txt', 'www.youtube.com_cookies.txt'):
        if os.path.exists(name):
            return name
    return None

YTDL_OPTS = {
    'format': 'ba/b',  # best audio, fallback to best overall
    'format_sort': ['abr', 'asr'],  # prefer higher audio bitrate
    'noplaylist': True,
    'quiet': True,
    'extract_flat': 'in_playlist',
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    # Stability optimizations
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'no_warnings': True,
    # Anti-bot bypass (Cookie File is the best method)
    'cookiefile': _get_cookie_file(),
    'extractor_args': {
        'youtube': {
            'player_client': ['mweb', 'default'],
        }
    }
}

# Safer FFMPEG options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# FFmpeg executable detection
def _get_ffmpeg_executable():
    if os.path.isfile('ffmpeg.exe'):
        return './ffmpeg.exe'
    if os.path.isfile('bin/ffmpeg.exe'):
        return 'bin/ffmpeg.exe'
    return 'ffmpeg'

FFMPEG_EXECUTABLE = _get_ffmpeg_executable()

try:
    import yt_dlp as youtube_dl
except ImportError:
    youtube_dl = None
    logger.error("yt_dlp is not installed! Music commands will not work.")


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
        loop = loop or asyncio.get_running_loop()
        ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            if not data['entries']:
                raise Exception('YouTube đang chặn server. Vui lòng thử lại sau hoặc dùng cookies.txt')
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)

        ffmpeg_opts = FFMPEG_OPTIONS.copy()
        if start_time > 0:
            current_before = ffmpeg_opts.get('before_options', '')
            ffmpeg_opts['before_options'] = f'{current_before} -ss {start_time}'

        return cls(discord.FFmpegPCMAudio(filename, executable=FFMPEG_EXECUTABLE, **ffmpeg_opts), data=data)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        ytdl = youtube_dl.YoutubeDL(YTDL_OPTS)

        if not search.startswith('http'):
            search = f"ytsearch:{search}"

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))

        if 'entries' in data:
            if not data['entries']:
                raise Exception("Could not find any songs matching your search.")
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

        asyncio.get_running_loop().create_task(self.player_loop())

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
                    async with timeout(300):  # 5 min timeout
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
                # Source creation (streaming)
                webpage_url = source_data.get('webpage_url', source_data.get('url'))
                source = await YTDLSource.from_url(webpage_url, loop=asyncio.get_running_loop(), stream=True, start_time=self.seek_position)
                self.current = source

                self.start_time = time.time() - self.seek_position
                self.pause_duration = 0
                self.pause_start = 0

                self.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
                await self.send_now_playing_embed(source_data)

            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                logger.error(f"Exception in player_loop: {error_trace}")

                try:
                    await self._channel.send(f'⚠️ Lỗi phát nhạc: {repr(e)}')
                except Exception:
                    pass
                # CRITICAL FIX: Clear current_data to prevent infinite loop of same error
                self.current_data = None
                self.next.set()

            await self.next.wait()
            self.current = None

    def get_current_position(self):
        if not self.current or not self.start_time:
            return 0
        current_pause = 0
        if self.pause_start > 0:
            current_pause = time.time() - self.pause_start
        return max(0, time.time() - self.start_time - self.pause_duration - current_pause)

    async def seek(self, seconds):
        if not self.voice_client or not self.current:
            return
        if seconds < 0:
            seconds = 0
        if self.current.duration and seconds > self.current.duration:
            seconds = self.current.duration - 1

        self.seeking = True
        self.seek_position = seconds
        self.voice_client.stop()

    async def stop(self):
        self.queue = asyncio.Queue()
        self.seeking = False
        self.loop_mode = 0
        if self.voice_client:
            self.voice_client.stop()

    async def skip(self):
        self.seeking = False
        # If loop song is on, force skip prevents replaying same song
        forced_loop_reset = False
        if self.loop_mode == 1:
            self.loop_mode = 0
            forced_loop_reset = True

        if self.voice_client:
            self.voice_client.stop()

        if forced_loop_reset:
            self.current_data = None
            self.loop_mode = 1

    def parse_duration(self, duration):
        if not duration:
            return "--:--"
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        return f"{int(minutes):02d}:{int(seconds):02d}"

    async def send_now_playing_embed(self, data):
        url = data.get('webpage_url') or data.get('url') or ''
        title = data.get('title', 'Unknown Title')

        embed = discord.Embed(title="🎶 Đang phát", description=f"[{title}]({url})", color=discord.Color.brand_green())
        if data.get('thumbnail'):
            embed.set_thumbnail(url=data['thumbnail'])
        embed.add_field(name="Thời lượng", value=self.parse_duration(data.get('duration')), inline=True)
        embed.add_field(
            name="Yêu cầu bởi",
            value=f"<@{data['requester_id']}>" if 'requester_id' in data else "Unknown",
            inline=True
        )

        status = []
        if self.loop_mode == 1:
            status.append("🔂 Lặp bài")
        if self.loop_mode == 2:
            status.append("🔁 Lặp hàng đợi")
        if status:
            embed.set_footer(text=" | ".join(status))

        view = MusicControls(self)
        if self.np:
            try:
                await self.np.delete()
            except Exception:
                pass
        self.np = await self._channel.send(embed=embed, view=view)


class AddSongModal(discord.ui.Modal, title="mỗi tháng 1 mv"):
    search_query = discord.ui.TextInput(label="Tên bài hát hoặc URL", placeholder="Nhập tên bài hát...", required=True)

    def __init__(self, player):
        super().__init__()
        self.player = player

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            query = self.search_query.value
            data = await YTDLSource.create_source(self.player, query, loop=asyncio.get_running_loop())

            # Ensure critical keys exist
            if 'webpage_url' not in data and 'url' in data:
                data['webpage_url'] = data['url']

            data['requester_id'] = interaction.user.id

            await self.player.queue.put(data)
            await interaction.followup.send(f"mỗi tháng 1 mv: **{data.get('title', 'Unknown')}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Lỗi: {e}", ephemeral=True)


class MusicControls(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player
        self.update_buttons()

    def update_buttons(self):
        # Update Loop Button style/label based on state
        loop_btn = [x for x in self.children if getattr(x, 'custom_id', None) == "loop_btn"]
        if not loop_btn:
            return
        loop_btn = loop_btn[0]
        if self.player.loop_mode == 0:
            loop_btn.label = "Loop Off"
            loop_btn.style = discord.ButtonStyle.secondary
            loop_btn.emoji = "➡️"
        elif self.player.loop_mode == 1:
            loop_btn.label = "Loop Song"
            loop_btn.style = discord.ButtonStyle.primary
            loop_btn.emoji = "🔂"
        elif self.player.loop_mode == 2:
            loop_btn.label = "Loop Queue"
            loop_btn.style = discord.ButtonStyle.success
            loop_btn.emoji = "🔁"

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ Bot không ở trong voice channel.", ephemeral=True)
            return
        if vc.is_playing():
            vc.pause()
            self.player.pause_start = time.time()
            await interaction.response.send_message("⏸️ po xì po", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            if self.player.pause_start > 0:
                self.player.pause_duration += (time.time() - self.player.pause_start)
                self.player.pause_start = 0
            await interaction.response.send_message("▶️ tieps tụcs", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Không có gì đang phát.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.skip()
        await interaction.response.send_message("⏩ oops, em lại càng muốn hát", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.player.stop()
        await interaction.response.send_message("⏹️ vay la cham het roi dung ko", ephemeral=True)

    @discord.ui.button(label="Loop Off", emoji="➡️", style=discord.ButtonStyle.secondary, custom_id="loop_btn", row=0)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Cycle modes: 0 -> 1 -> 2 -> 0
        self.player.loop_mode = (self.player.loop_mode + 1) % 3
        self.update_buttons()
        await interaction.response.edit_message(view=self)  # Update view in-place

    @discord.ui.button(label="Add Song", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def add_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddSongModal(self.player))

    @discord.ui.button(label="-10s", style=discord.ButtonStyle.secondary, row=2)
    async def rewind(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._seek_relative(interaction, -10)

    @discord.ui.button(label="+10s", style=discord.ButtonStyle.secondary, row=2)
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._seek_relative(interaction, 10)

    async def _seek_relative(self, interaction, seconds):
        if not self.player.current:
            await interaction.response.send_message("❌ Không có gì đang phát.", ephemeral=True)
            return
        pos = self.player.get_current_position()
        new_pos = max(0, pos + seconds)
        await self.player.seek(new_pos)
        await interaction.response.send_message(f"⏩ Seeking to {int(new_pos)}s", ephemeral=True)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def cog_unload(self):
        """Cleanup all players when cog is unloaded."""
        for player in self.players.values():
            asyncio.ensure_future(player.stop())
        self.players.clear()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Cleanup player when bot is disconnected from voice."""
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            # Bot was disconnected
            guild_id = before.channel.guild.id
            if guild_id in self.players:
                await self.players[guild_id].stop()
                del self.players[guild_id]

    def get_player(self, ctx):
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = MusicPlayer(ctx, self)
        return self.players[ctx.guild.id]

    async def _join(self, ctx):
        if not ctx.author.voice:
            await ctx.reply("❌ vao voice roi nói chuyen voi chi")
            return False
        channel = ctx.author.voice.channel
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.reply(f"helu this is minchong bo't {channel.name}")
        return True

    # --- Slash Commands ---
    @app_commands.command(name="join")
    async def join_slash(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self._join(ctx)

    @app_commands.command(name="leave")
    async def leave_slash(self, interaction: discord.Interaction):
        await self._leave(await commands.Context.from_interaction(interaction))

    @app_commands.command(name="play")
    async def play_slash(self, interaction: discord.Interaction, search: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self._play(ctx, search)

    @app_commands.command(name="loop")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value=0),
        app_commands.Choice(name="Song", value=1),
        app_commands.Choice(name="Queue", value=2)
    ])
    async def loop_slash(self, interaction: discord.Interaction, mode: int):
        player = self.get_player(await commands.Context.from_interaction(interaction))
        player.loop_mode = mode
        modes = ["Off", "Song", "Queue"]
        await interaction.response.send_message(f"🔁 Loop mode: **{modes[mode]}**")

    @app_commands.command(name="queue")
    async def queue_slash(self, interaction: discord.Interaction):
        await self._queue(await commands.Context.from_interaction(interaction))

    @app_commands.command(name="clear_queue", description="vay la tat ca do xuong song")
    async def clear_queue_slash(self, interaction: discord.Interaction):
        await self._clear_queue(await commands.Context.from_interaction(interaction))

    @app_commands.command(name="skip")
    async def skip_slash(self, interaction: discord.Interaction):
        await self._skip(await commands.Context.from_interaction(interaction))

    @app_commands.command(name="stop")
    async def stop_slash(self, interaction: discord.Interaction):
        await self._stop(await commands.Context.from_interaction(interaction))

    # --- Text Commands (Prefixed) ---
    @commands.command(name="join", aliases=["j"])
    async def join_text(self, ctx):
        await self._join(ctx)

    @commands.command(name="leave", aliases=["l", "disconnect"])
    async def leave_text(self, ctx):
        await self._leave(ctx)

    @commands.command(name="play", aliases=["p"])
    async def play_text(self, ctx, *, search):
        await self._play(ctx, search)

    @commands.command(name="skip", aliases=["s", "next"])
    async def skip_text(self, ctx):
        await self._skip(ctx)

    @commands.command(name="stop", aliases=["st"])
    async def stop_text(self, ctx):
        await self._stop(ctx)

    @commands.command(name="queue", aliases=["q"])
    async def queue_text(self, ctx):
        await self._queue(ctx)

    @commands.command(name="clear_queue", aliases=["c", "cq"])
    async def clear_queue_text(self, ctx):
        await self._clear_queue(ctx)

    @commands.command(name="loop")
    async def loop_text(self, ctx):
        player = self.get_player(ctx)
        player.loop_mode = (player.loop_mode + 1) % 3
        modes = ["Off", "Song", "Queue"]
        await ctx.reply(f"🔁 Loop mode: **{modes[player.loop_mode]}**")

    # --- Shared Logic ---
    async def _leave(self, ctx):
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()
            if ctx.guild.id in self.players:
                del self.players[ctx.guild.id]
            await ctx.reply("chac anh phai roi xa noi da...y")
        else:
            await ctx.reply("❌ vào voice roi noi chien voi chi")

    async def _play(self, ctx, search):
        if not ctx.guild.voice_client:
            if not await self._join(ctx):
                return

        # Determine valid reply method (slash or text)
        reply = ctx.send if isinstance(ctx, commands.Context) else ctx.interaction.followup.send
        if hasattr(ctx, 'interaction') and ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer()
            reply = ctx.interaction.followup.send

        player = self.get_player(ctx)

        try:
            data = await YTDLSource.create_source(player, search, loop=asyncio.get_running_loop())
            data['requester_id'] = ctx.author.id
            await player.queue.put(data)
            await reply(f"va sau day la: **{data['title']}**")
        except Exception as e:
            logger.error(f"Error playing '{search}': {e}")
            await reply(f"❌ Error: {e}")

    async def _skip(self, ctx):
        player = self.get_player(ctx)
        await player.skip()
        if isinstance(ctx, commands.Context):
            await ctx.reply("⏩ di nhien roi.. won dong la lua chon cua anduchin.")
        else:
            await ctx.interaction.response.send_message("⏩ di nhien roi.. won dong la lua chon cua anduchin.")

    async def _stop(self, ctx):
        player = self.get_player(ctx)
        await player.stop()
        if isinstance(ctx, commands.Context):
            await ctx.reply("⏹️ min chong xin phep di ve")
        else:
            await ctx.interaction.response.send_message("⏹️ min chong xin phep di ve")

    async def _queue(self, ctx):
        player = self.get_player(ctx)
        if player.queue.empty():
            msg = "📭 co gi dau mà..xóa"
            if isinstance(ctx, commands.Context):
                await ctx.reply(msg)
            else:
                await ctx.interaction.response.send_message(msg)
            return

        upcoming = list(itertools.islice(player.queue._queue, 0, 10))
        desc = ""
        for i, song in enumerate(upcoming):
            desc += f"**{i+1}.** {song['title']}\n"

        embed = discord.Embed(title=f"Queue ({player.queue.qsize()})", description=desc)
        if isinstance(ctx, commands.Context):
            await ctx.send(embed=embed)
        else:
            await ctx.interaction.response.send_message(embed=embed)

    async def _clear_queue(self, ctx):
        player = self.get_player(ctx)
        player.queue = asyncio.Queue()
        player.loop_mode = 0
        msg = "🗑️ con gi nữa.đâu"
        if isinstance(ctx, commands.Context):
            await ctx.reply(msg)
        else:
            await ctx.interaction.response.send_message(msg)


async def setup(bot):
    await bot.add_cog(Music(bot))
