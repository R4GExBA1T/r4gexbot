"""Staff Logs: transparent moderation action log.

Logs bans, kicks, timeouts, message deletes to a configured channel.
Admins set the channel via /config (log_channel).
"""
import discord
from discord.ext import commands
from datetime import datetime, timezone

RUST_COLOR = 0xCE6A2C


class StaffLogs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_log_channel(self, guild_id: int):
        """Get the configured log channel, or None."""
        config = self.bot.get_cog("Config")
        if not config:
            return None
        try:
            channel_id = await config.get_int(guild_id, "log_channel")
            if channel_id == 0:
                return None
            return self.bot.get_channel(channel_id)
        except:
            return None

    async def _log(self, guild_id: int, title: str, description: str, color: int):
        channel = await self._get_log_channel(guild_id)
        if not channel:
            return
        em = discord.Embed(title=title, description=description, color=color,
                           timestamp=datetime.now(timezone.utc))
        try:
            await channel.send(embed=em)
        except:
            pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self._log(guild.id, "🔨 Member Banned",
                        f"**{user}** (`{user.id}`) was banned.", 0xE74C3C)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self._log(guild.id, "✅ Member Unbanned",
                        f"**{user}** (`{user.id}`) was unbanned.", 0x57F287)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Could be kick or leave - we log it as "left"
        await self._log(member.guild.id, "👋 Member Left",
                        f"**{member}** (`{member.id}`) left the server.", 0x95A5A6)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Timeout detection
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                await self._log(after.guild.id, "⏰ Member Timed Out",
                                f"**{after}** was timed out until <t:{int(after.timed_out_until.timestamp())}:F>.",
                                0xF39C12)
            else:
                await self._log(after.guild.id, "✅ Timeout Removed",
                                f"**{after}**'s timeout was removed.", 0x57F287)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild and not message.author.bot:
            content = message.content[:200] if message.content else "*no text*"
            await self._log(message.guild.id, "🗑️ Message Deleted",
                            f"**{message.author}** in {message.channel.mention}:\n{content}",
                            0x95A5A6)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffLogs(bot))
