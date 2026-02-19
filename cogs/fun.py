import discord
from discord.ext import commands
import json
import random
import os
import google.generativeai as genai

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.food_data = self.load_food_data()
        self.setup_gemini()

    def load_food_data(self):
        try:
            with open(os.path.join('data', 'food.json'), 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading food data: {e}")
            return {}

    def setup_gemini(self):
        api_key = os.getenv('GEMINI_API_KEY')
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-pro')
            self.has_ai = True
        else:
            self.has_ai = False

    async def get_food_suggestion(self, meal_type):
        if self.has_ai:
            try:
                # Prompt engineering for "Minchong" personality
                prompt = (
                    f"Bạn là bot Minchong, một trợ lý ảo vui tính, sử dụng ngôn ngữ teen code nhẹ nhàng, thân thiện. "
                    f"Hãy gợi ý MỘT món ăn {meal_type} ngon miệng ở Việt Nam. "
                    f"Chỉ trả lời tên món ăn và một câu chúc ngắn gọn, vui vẻ. Không giải thích dài dòng."
                )
                response = await self.model.generate_content_async(prompt)
                return response.text
            except Exception as e:
                print(f"Gemini API Error: {e}")
                # Fallback to local data if AI fails
        
        # Local fallback
        key_map = {"sáng": "breakfast", "trưa": "lunch", "tối": "dinner"}
        key = key_map.get(meal_type)
        if key and key in self.food_data:
            dish = random.choice(self.food_data[key])
            return f"Món {meal_type} hôm nay: {dish} nhaa 😋"
        return f"Hic, không tìm thấy món {meal_type} nào trong menu rùi 😭"

    @commands.command(name="ansang")
    async def ansang(self, ctx):
        suggestion = await self.get_food_suggestion("sáng")
        await ctx.send(suggestion)

    @commands.command(name="antrua")
    async def antrua(self, ctx):
        suggestion = await self.get_food_suggestion("trưa")
        await ctx.send(suggestion)

    @commands.command(name="antoi")
    async def antoi(self, ctx):
        suggestion = await self.get_food_suggestion("tối")
        await ctx.send(suggestion)

async def setup(bot):
    await bot.add_cog(Fun(bot))
