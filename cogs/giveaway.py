"""Giveaways: timed prize draws with auto winner picking."""
import asyncio
import io
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C


def error_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"❌ {msg}", color=0xE74C3C)


def success_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"✅ {msg}", color=RUST_COLOR)


class GiveawayEnterView(discord.ui.View):
    """Persistent enter button for a giveaway message."""

    def __init__(self, cog: "Giveaway", giveaway_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id

    @discord.ui.button(label="🎉 Enter", style=discord.ButtonStyle.primary,
                       custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction,
                    button: discord.ui.Button):
        await self.cog.enter_giveaway(interaction, self.giveaway_id)


class Giveaway(commands.Cog):
    """Giveaway system: /giveaway create, auto-draws winners when time ends."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        await self._ensure_table()

    async def _ensure_table(self):
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS giveaways (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   guild_id INTEGER, channel_id INTEGER, message_id INTEGER,
                   prize TEXT, winners_count INTEGER,
                   ends_at TEXT, ended INTEGER DEFAULT 0,
                   created_by INTEGER)""")
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS giveaway_entries (
                   giveaway_id INTEGER, user_id INTEGER,
                   PRIMARY KEY (giveaway_id, user_id))""")
        await self.bot.economy.db.commit()

    @staticmethod
    def _parse_duration(text: str) -> timedelta | None:
        """Parse e.g. '1h', '30m', '2d', '1d12h' into a timedelta."""
        import re
        total = timedelta()
        found = False
        for amount, unit in re.findall(r"(\d+)\s*([smhd])", text.lower()):
            amount = int(amount)
            if unit == "s":
                total += timedelta(seconds=amount)
            elif unit == "m":
                total += timedelta(minutes=amount)
            elif unit == "h":
                total += timedelta(hours=amount)
            elif unit == "d":
                total += timedelta(days=amount)
            found = True
        if not found:
            return None
        # Sanity limits: 1 minute to 30 days
        if total < timedelta(minutes=1) or total > timedelta(days=30):
            return None
        return total

    @staticmethod
    def _giveaway_embed(prize: str, ends_at: datetime, winners: int,
                        entries: int = 0, winner_names: str | None = None,
                        ended: bool = False) -> discord.Embed:
        color = 0x5865F2 if not ended else 0x57F287
        em = discord.Embed(
            title=f"🎉 GIVEAWAY: {prize}",
            description=(f"**{winners}** winner{'s' if winners != 1 else ''}\n"
                         f"📥 **{entries}** entries"),
            color=color,
            timestamp=datetime.now(timezone.utc))
        if ended and winner_names:
            em.add_field(name="🏆 Winners", value=winner_names, inline=False)
        elif not ended:
            ts = int(ends_at.timestamp())
            em.add_field(name="⏰ Ends", value=f"<t:{ts}:R>", inline=False)
        em.set_footer(text="Click 🎉 Enter below to join!")
        return em

    async def _schedule_end(self, giveaway_id: int, delay: float):
        """Wait `delay` seconds then end the giveaway."""
        try:
            await asyncio.sleep(delay)
            await self._end_giveaway(giveaway_id)
        except asyncio.CancelledError:
            pass
        finally:
            self._tasks.pop(giveaway_id, None)

    @app_commands.command(name="giveaway", description="Run a timed giveaway")
    @app_commands.describe(action="What to do",
                           prize="What's being given away",
                           duration="How long: e.g. 30m, 2h, 1d",
                           winners="How many winners (default 1)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Create", value="create"),
        app_commands.Choice(name="End now", value="end"),
        app_commands.Choice(name="Reroll", value="reroll"),
    ])
    async def giveaway(self, interaction: discord.Interaction,
                       action: str, prize: str = "", duration: str = "1h",
                       winners: int = 1):
        await interaction.response.defer()

        if not interaction.user.guild_permissions.manage_messages:
            await interaction.followup.send(
                embed=error_embed("Staff only — you need Manage Messages."), ephemeral=True)
            return

        if action == "create":
            if not prize:
                await interaction.followup.send(
                    embed=error_embed("Give a prize, e.g. `prize: VIP 30 Days`."), ephemeral=True)
                return
            delta = self._parse_duration(duration)
            if delta is None:
                await interaction.followup.send(
                    embed=error_embed("Bad duration. Use like `30m`, `2h`, `1d`. (1m–30d)"),
                    ephemeral=True)
                return
            winners = max(1, min(10, winners))
            ends_at = datetime.now(timezone.utc) + delta

            cur = await self.bot.economy.db.execute(
                "INSERT INTO giveaways (guild_id, channel_id, prize, winners_count, ends_at, created_by)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (interaction.guild_id, interaction.channel_id, prize, winners,
                 ends_at.isoformat(), interaction.user.id))
            await self.bot.economy.db.commit()
            gid = cur.lastrowid

            view = GiveawayEnterView(self, gid)
            msg = await interaction.followup.send(
                embed=self._giveaway_embed(prize, ends_at, winners),
                view=view)
            await self.bot.economy.db.execute(
                "UPDATE giveaways SET message_id = ? WHERE id = ?",
                (msg.id, gid))
            await self.bot.economy.db.commit()

            self._tasks[gid] = asyncio.create_task(
                self._schedule_end(gid, delta.total_seconds()))

        elif action == "end":
            # End the most recent active giveaway in this channel
            cur = await self.bot.economy.db.execute(
                "SELECT id FROM giveaways WHERE guild_id = ? AND channel_id = ? AND ended = 0"
                " ORDER BY id DESC LIMIT 1",
                (interaction.guild_id, interaction.channel_id))
            row = await cur.fetchone()
            if not row:
                await interaction.followup.send(
                    embed=error_embed("No active giveaway in this channel."), ephemeral=True)
                return
            await self._end_giveaway(row[0])
            await interaction.followup.send(embed=success_embed("Giveaway ended."), ephemeral=True)

        elif action == "reroll":
            cur = await self.bot.economy.db.execute(
                "SELECT id FROM giveaways WHERE guild_id = ? AND channel_id = ? AND ended = 1"
                " ORDER BY id DESC LIMIT 1",
                (interaction.guild_id, interaction.channel_id))
            row = await cur.fetchone()
            if not row:
                await interaction.followup.send(
                    embed=error_embed("No finished giveaway in this channel to reroll."), ephemeral=True)
                return
            await self._reroll(row[0])
            await interaction.followup.send(embed=success_embed("Rerolled!"), ephemeral=True)

    async def enter_giveaway(self, interaction: discord.Interaction, giveaway_id: int):
        await interaction.response.defer(ephemeral=True)
        cur = await self.bot.economy.db.execute(
            "SELECT ended FROM giveaways WHERE id = ?", (giveaway_id,))
        row = await cur.fetchone()
        if not row or row[0]:
            await interaction.followup.send(
                embed=error_embed("This giveaway has ended."), ephemeral=True)
            return
        try:
            await self.bot.economy.db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                (giveaway_id, interaction.user.id))
            await self.bot.economy.db.commit()
        except Exception:
            await interaction.followup.send(
                embed=error_embed("You're already entered!"), ephemeral=True)
            return
        cur = await self.bot.economy.db.execute(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,))
        entries = (await cur.fetchone())[0]
        await interaction.followup.send(
            embed=success_embed(f"You're in! ({entries} total entries)"), ephemeral=True)
        # Update the entry count on the message
        await self._refresh_message(giveaway_id)

    async def _refresh_message(self, giveaway_id: int):
        cur = await self.bot.economy.db.execute(
            "SELECT channel_id, message_id, prize, winners_count, ends_at FROM giveaways WHERE id = ?",
            (giveaway_id,))
        row = await cur.fetchone()
        if not row:
            return
        channel_id, message_id, prize, winners, ends_at = row
        cur = await self.bot.economy.db.execute(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,))
        entries = (await cur.fetchone())[0]
        try:
            channel = self.bot.get_channel(channel_id)
            msg = await channel.fetch_message(message_id)
            await msg.edit(
                embed=self._giveaway_embed(prize, datetime.fromisoformat(ends_at),
                                           winners, entries))
        except Exception:
            pass

    def _pick_winners(self, entries: list[int], count: int) -> list[int]:
        if not entries:
            return []
        count = min(count, len(entries))
        return random.sample(entries, count)

    async def _end_giveaway(self, giveaway_id: int):
        task = self._tasks.pop(giveaway_id, None)
        if task:
            task.cancel()
        cur = await self.bot.economy.db.execute(
            "SELECT channel_id, message_id, prize, winners_count, ended FROM giveaways WHERE id = ?",
            (giveaway_id,))
        row = await cur.fetchone()
        if not row or row[4]:
            return
        channel_id, message_id, prize, winners_count, _ = row
        cur = await self.bot.economy.db.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,))
        entries = [r[0] for r in await cur.fetchall()]
        winner_ids = self._pick_winners(entries, winners_count)

        await self.bot.economy.db.execute(
            "UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))
        await self.bot.economy.db.commit()

        winner_names = ""
        if winner_ids:
            winner_names = ", ".join(f"<@{uid}>" for uid in winner_ids)
        else:
            winner_names = "No entries 😢"

        try:
            channel = self.bot.get_channel(channel_id)
            msg = await channel.fetch_message(message_id)
            ends_at = datetime.now(timezone.utc)
            em = self._giveaway_embed(prize, ends_at, winners_count,
                                      len(entries), winner_names, ended=True)
            em.title = f"🎉 GIVEAWAY ENDED: {prize}"
            await msg.edit(embed=em, view=None)
            ping = " ".join(f"<@{uid}>" for uid in winner_ids)
            await channel.send(
                f"🎉 Congratulations {ping}! You won **{prize}**!"
                if ping else f"🎉 Giveaway for **{prize}** ended with no entries.")
        except Exception:
            pass

    async def _reroll(self, giveaway_id: int):
        cur = await self.bot.economy.db.execute(
            "SELECT channel_id, message_id, prize, winners_count FROM giveaways WHERE id = ?",
            (giveaway_id,))
        row = await cur.fetchone()
        if not row:
            return
        channel_id, message_id, prize, winners_count = row
        cur = await self.bot.economy.db.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,))
        entries = [r[0] for r in await cur.fetchall()]
        winner_ids = self._pick_winners(entries, winners_count)
        winner_names = ", ".join(f"<@{uid}>" for uid in winner_ids) if winner_ids else "No entries 😢"
        try:
            channel = self.bot.get_channel(channel_id)
            msg = await channel.fetch_message(message_id)
            em = self._giveaway_embed(prize, datetime.now(timezone.utc),
                                      winners_count, len(entries), winner_names, ended=True)
            em.title = f"🎉 GIVEAWAY ENDED (REROLLED): {prize}"
            await msg.edit(embed=em)
            ping = " ".join(f"<@{uid}>" for uid in winner_ids)
            if ping:
                await channel.send(f"🎲 Reroll! New winner{'s' if len(winner_ids) != 1 else ''}: {ping} — **{prize}**!")
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))
