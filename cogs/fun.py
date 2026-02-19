import discord
from discord.ext import commands
import json
import random
import os

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.food_data = self.load_food_data()

    def load_food_data(self):
        try:
            with open(os.path.join('data', 'food.json'), 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading food data: {e}")
            return {}

    @commands.command(name="ansang")
    async def ansang(self, ctx):
        if 'breakfast' in self.food_data:
            await ctx.send(f"Món ăn sáng hôm nay: {random.choice(self.food_data['breakfast'])}")
        else:
            await ctx.send("Không tìm thấy dữ liệu món ăn sáng.")

    @commands.command(name="antrua")
    async def antrua(self, ctx):
        if 'lunch' in self.food_data:
             await ctx.send(f"Món ăn trưa hôm nay: {random.choice(self.food_data['lunch'])}")
        else:
             await ctx.send("Không tìm thấy dữ liệu món ăn trưa.")

    @commands.command(name="antoi")
    async def antoi(self, ctx):
        if 'dinner' in self.food_data:
             await ctx.send(f"Món ăn tối hôm nay: {random.choice(self.food_data['dinner'])}")
        else:
             await ctx.send("Không tìm thấy dữ liệu món ăn tối.")

async def setup(bot):
    await bot.add_cog(Fun(bot))
