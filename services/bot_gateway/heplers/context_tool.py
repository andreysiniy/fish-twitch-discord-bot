
async def get_channel_id(ctx):
    channel_id = (await ctx.message.channel.user()).id.__str__()
    return channel_id