"""Wipe Countdown: automated wipe timer with hype announcements.

/wipe set <date> — set the wipe date (admin)
  e.g. /wipe set date:2026-11-01 time:18:00
/wipe info — see time until wipe
/wipe clear — remove the wipe timer (admin)

Auto-posts countdown updates in the channel where it was set.
"""
import asyncio
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C


class Wipe(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS wipe_config (
                   guild_id INTEGER PRIMARY KEY,
                   wipe_at TEXT, channel_id INTEGER)""")
        await self.bot.economy.db.commit()
        # Resume countdown if one was set
        self._task = asyncio.create_task(self._countdown_loop())

    def cog_unload(self):
        if self._task:
            self._task.cancel()

    async def _countdown_loop(self):
        """Check every 5 minutes; post milestones."""
        await asyncio.sleep(10)  # let bot start
        posted = set()  # (guild_id, milestone) already announced
        while True:
            try:
                cur = await self.bot.economy.db.execute(
                    "SELECT guild_id, wipe_at, channel_id FROM wipe_config")
                rows = await cur.fetchall()
                now = datetime.now(timezone.utc)
                for guild_id, wipe_at, channel_id in rows:
                    wipe_dt = datetime.fromisoformat(wipe_at)
                    delta = wipe_dt - now
                    if delta.total_seconds() <= 0:
                        # Wipe time! Announce and clear
                        if (guild_id, "wipe") not in posted:
                            await self._announce(guild_id, channel_id,
                                                 "🔥 **WIPE IS LIVE!** 🔥\nThe server has wiped! Fresh start, good luck!")
                            posted.add((guild_id, "wipe"))
                            await self.bot.economy.db.execute(
                                "DELETE FROM wipe_config WHERE guild_id = ?", (guild_id,))
                            await self.bot.economy.db.commit()
                        continue
                    # Milestones: 7d, 3d, 1d, 12h, 6h, 1h, 30m, 10m
                    # Post the MOST URGENT milestone we've reached (smallest threshold first)
                    milestones = [
                        (timedelta(minutes=10), "10m", "🔥 **10 MINUTES** until wipe! Get to a safe spot!"),
                        (timedelta(minutes=30), "30m", "🔥 **30 MINUTES** until wipe!"),
                        (timedelta(hours=1), "1h", "⏰ **1 HOUR** until wipe! Final preparations!"),
                        (timedelta(hours=6), "6h", "⏰ **6 hours** until wipe!"),
                        (timedelta(hours=12), "12h", "⏰ **12 hours** until wipe!"),
                        (timedelta(days=1), "1d", "📅 **24 hours** until wipe! Get your last raids in!"),
                        (timedelta(days=3), "3d", "📅 **3 days** until wipe!"),
                        (timedelta(days=7), "7d", "📅 **7 days** until wipe!"),
                    ]
                    for threshold, key, msg in milestones:
                        if delta <= threshold and (guild_id, key) not in posted:
                            await self._announce(guild_id, channel_id, msg)
                            posted.add((guild_id, key))
                            break
                    # Mark all larger milestones as posted so we don't backfill
                    # e.g. if wipe is 18h away, don't later post "7 days" or "3 days"
                    for threshold, key, msg in milestones:
                        if delta <= threshold:
                            posted.add((guild_id, key))
            except Exception:
                pass
            await asyncio.sleep(300)  # check every 5 min

    async def _announce(self, guild_id: int, channel_id: int, msg: str):
        try:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(msg)
        except Exception:
            pass

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @staticmethod
    def _fmt_delta(delta: timedelta) -> str:
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        mins, _ = divmod(rem, 60)
        parts = []
        if days: parts.append(f"{days}d")
        if hours: parts.append(f"{hours}h")
        if mins: parts.append(f"{mins}m")
        return " ".join(parts) or "less than a minute"

    @app_commands.command(name="wipe", description="⏰ Wipe countdown timer")
    @app_commands.describe(action="What to do",
                           date="Wipe date (YYYY-MM-DD, for set)",
                           time="Wipe time (HH:MM 24h UTC, for set)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Set wipe timer", value="set"),
        app_commands.Choice(name="Check countdown", value="info"),
        app_commands.Choice(name="Clear timer", value="clear"),
    ])
    async def wipe(self, interaction: discord.Interaction,
                   action: str, date: str = "", time: str = ""):
        await interaction.response.defer()

        if action == "info":
            cur = await self.bot.economy.db.execute(
                "SELECT wipe_at FROM wipe_config WHERE guild_id = ?",
                (interaction.guild_id,))
            row = await cur.fetchone()
            if not row:
                await interaction.followup.send(
                    "📅 No wipe scheduled. Admins can set one with `/wipe set`.")
                return
            wipe_dt = datetime.fromisoformat(row[0])
            delta = wipe_dt - datetime.now(timezone.utc)
            if delta.total_seconds() <= 0:
                await interaction.followup.send("🔥 Wipe is happening now!")
                return
            ts = int(wipe_dt.timestamp())
            em = discord.Embed(title="⏰ Wipe Countdown", color=RUST_COLOR,
                               description=f"**{self._fmt_delta(delta)}** remaining")
            em.add_field(name="Wipe time", value=f"<t:{ts}:F>\n<t:{ts}:R>", inline=False)
            await interaction.followup.send(embed=em)
            return

        # set / clear need admin
        if not self._is_admin(interaction):
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return

        if action == "set":
            if not date or not time:
                await interaction.followup.send(
                    "❌ Give date and time! e.g. `/wipe set date:2026-11-01 time:18:00` (UTC)",
                    ephemeral=True)
                return
            try:
                wipe_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
                wipe_dt = wipe_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                await interaction.followup.send(
                    "❌ Bad format! Use `date:2026-11-01 time:18:00` (24h UTC).",
                    ephemeral=True)
                return
            if wipe_dt <= datetime.now(timezone.utc):
                await interaction.followup.send(
                    "❌ That time is in the past!", ephemeral=True)
                return
            await self.bot.economy.db.execute(
                """INSERT OR REPLACE INTO wipe_config (guild_id, wipe_at, channel_id)
                   VALUES (?, ?, ?)""",
                (interaction.guild_id, wipe_dt.isoformat(), interaction.channel_id))
            await self.bot.economy.db.commit()
            ts = int(wipe_dt.timestamp())
            await interaction.followup.send(
                f"✅ Wipe scheduled for <t:{ts}:F> (<t:{ts}:R>)!\n"
                f"Countdown updates will post in this channel.")

        elif action == "clear":
            await self.bot.economy.db.execute(
                "DELETE FROM wipe_config WHERE guild_id = ?", (interaction.guild_id,))
            await self.bot.economy.db.commit()
            await interaction.followup.send("✅ Wipe timer cleared.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wipe(bot))
