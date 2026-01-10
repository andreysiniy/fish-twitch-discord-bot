import os
import aiohttp
from twitchio.ext import commands

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=os.environ['TWITCH_TOKEN'],
            prefix='!',
            initial_channels=[os.environ['INITIAL_CHANNELS']],
            client_secret=os.environ.get('TWITCH_CLIENT_SECRET', None),
            client_id=os.environ.get('TWITCH_CLIENT_ID', None),
            bot_id=os.environ.get('BOT_NICK', None)
        )
        self.engine_url = os.environ['ENGINE_URL']

    async def event_ready(self):
        print(f'Logged in as | {self.nick}')

    @commands.command(name='fish')
    async def fish_command(self, ctx):
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_name": ctx.channel.name
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.engine_url}/v1/fish", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await ctx.send(data['text'])
                    else:
                        await ctx.send(" :( ")
        except Exception as e:
            print(f"Error calling engine: {e}")
            await ctx.send("Lost my fishing rod...")

bot = Bot()
bot.run()