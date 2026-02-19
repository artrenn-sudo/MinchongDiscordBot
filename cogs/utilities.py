import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import aiohttp
import asyncio
import datetime

class Utilities(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduled_messages.start()
        
        # Scheduled reminders: (channel_id, hour, minute, message)
        self.reminders = [
            (123456789012345678, 20, 0, "⏰ Nhắc nhở: Đã đến giờ nghỉ ngơi!"),
            (123456789012345678, 8, 0, "🌞 Chào buổi sáng! Đừng quên uống nước nhé!")
        ]

    def cog_unload(self):
        self.scheduled_messages.cancel()

    @app_commands.command(name="weather", description="Xem thời tiết của một thành phố")
    async def weather(self, interaction: discord.Interaction, city: str):
        api_key = os.getenv('OPENWEATHER_API_KEY')
        if not api_key:
            await interaction.response.send_message("❌ API Key chưa được cấu hình.", ephemeral=True)
            return

        async with aiohttp.ClientSession() as session:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    temp = data['main']['temp']
                    desc = data['weather'][0]['description']
                    await interaction.response.send_message(f"🌤 Thời tiết ở {city}: {temp}°C, {desc}")
                else:
                    await interaction.response.send_message("❌ Không tìm thấy thành phố hoặc lỗi API.")

    @app_commands.command(name="poll", description="Tạo poll nhanh")
    async def poll(self, interaction: discord.Interaction, question: str):
        embed = discord.Embed(title="📊 Poll", description=question, color=discord.Color.blue())
        await interaction.response.send_message("Poll đã được tạo!", ephemeral=True)
        # We need to send the message to the channel to add reactions
        poll_message = await interaction.channel.send(embed=embed)
        await poll_message.add_reaction("✅")
        await poll_message.add_reaction("❌")

    @app_commands.command(name="remindme", description="Gửi tin nhắn nhắc nhở sau một khoảng thời gian")
    async def remindme(self, interaction: discord.Interaction, time: int, message: str):
        await interaction.response.send_message(f"⏳ Nhắc bạn sau {time} giây", ephemeral=True)
        await asyncio.sleep(time)
        await interaction.channel.send(f"⏰ {interaction.user.mention} {message}")

    @tasks.loop(minutes=1)
    async def scheduled_messages(self):
        now = datetime.datetime.now()
        for channel_id, hour, minute, message in self.reminders:
            if now.hour == hour and now.minute == minute:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    await channel.send(message)

    @scheduled_messages.before_loop
    async def before_scheduled_messages(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Utilities(bot))
