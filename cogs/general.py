import discord
from discord.ext import commands
from discord import app_commands
import asyncio

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="hello")
    async def hello(self, ctx):
        await ctx.send("halluuuu! con la minchongieeeee 😎")

    @commands.command(name="ping")
    async def ping(self, ctx):
        await ctx.send(f"Pong! {round(self.bot.latency * 1000)}ms")

    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 10):
        """Xóa `amount` tin nhắn trong kênh (Mặc định: 10)."""
        amount = max(1, min(amount, 100))
        # Purge includes the command message if using ctx.message inside purge logic, 
        # but purge usually deletes 'limit' messages.
        # Original logic: deleted = await ctx.channel.purge(limit=amount + 1)
        
        try:
            deleted = await ctx.channel.purge(limit=amount + 1) 
            # Subtract 1 because the command message itself was deleted
            count = max(0, len(deleted) - 1) 
            msg = await ctx.send(f"✅ Đã xóa {count} tin nhắn.")
            await asyncio.sleep(5)
            await msg.delete()
        except discord.Forbidden:
             await ctx.send("❌ Bot không có quyền xóa tin nhắn.", delete_after=5)

    @clear.error
    async def clear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Bạn không có quyền xóa tin nhắn.", delete_after=5)

    # Slash command equivalent
    @app_commands.command(name="clear", description="Xóa tin nhắn trong kênh")
    @app_commands.describe(amount="Số tin nhắn muốn xóa (1-100).")
    async def clear_slash(self, interaction: discord.Interaction, amount: int = 10):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Bạn không có quyền xóa tin nhắn.", ephemeral=True)
            return
        
        amount = max(1, min(amount, 100))
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ Đã xóa {len(deleted)} tin nhắn.", ephemeral=True)
        except discord.Forbidden:
             await interaction.followup.send("❌ Bot không có quyền xóa tin nhắn.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Lỗi: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(General(bot))
