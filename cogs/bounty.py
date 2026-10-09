"""Bounty Board: players place bounties on each other, hunters claim them.

/bounty place <target> <amount> <reason> — put a price on someone's head
/bounty board — see active bounties
/bounty claim <id> — claim a bounty (with proof)
/bounty cancel <id> — cancel your bounty (refund)
"""
import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C
GOLD = 0xFFD700


class Bounty(commands.Cog):
    """Player-driven bounty system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS bounties (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   guild_id INTEGER, target_id INTEGER, target_name TEXT,
                   placer_id INTEGER, placer_name TEXT,
                   amount INTEGER, reason TEXT,
                   status TEXT DEFAULT 'active',
                   created_at TEXT)""")
        await self.bot.economy.db.commit()

    @app_commands.command(name="bounty", description="🎯 Bounty board — place bounties, hunt targets")
    @app_commands.describe(action="What to do",
                           target="Who to place the bounty on (for place)",
                           amount="Scrap reward (for place)",
                           reason="Why (for place)",
                           bounty_id="Bounty ID (for claim/cancel)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Place a bounty", value="place"),
        app_commands.Choice(name="View board", value="board"),
        app_commands.Choice(name="Claim a bounty", value="claim"),
        app_commands.Choice(name="Cancel your bounty", value="cancel"),
    ])
    async def bounty(self, interaction: discord.Interaction,
                     action: str, target: discord.Member = None,
                     amount: int = 0, reason: str = "",
                     bounty_id: int = 0):
        await interaction.response.defer()

        if action == "place":
            if not target:
                await interaction.followup.send("❌ Pick a target!", ephemeral=True)
                return
            if target.id == interaction.user.id:
                await interaction.followup.send("❌ Can't bounty yourself!", ephemeral=True)
                return
            if target.bot:
                await interaction.followup.send("❌ Can't bounty bots!", ephemeral=True)
                return
            if amount < 50:
                await interaction.followup.send("❌ Minimum bounty is 50 Scrap.", ephemeral=True)
                return
            # Check balance and deduct
            from services.economy import EconomyError
            try:
                await self.bot.economy.deduct_scrap(interaction.user.id, amount)
            except EconomyError:
                await interaction.followup.send(
                    "❌ Not enough Scrap!", ephemeral=True)
                return
            from datetime import datetime, timezone
            cur = await self.bot.economy.db.execute(
                """INSERT INTO bounties
                   (guild_id, target_id, target_name, placer_id, placer_name, amount, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (interaction.guild_id, target.id, target.display_name,
                 interaction.user.id, interaction.user.display_name,
                 amount, reason or "No reason given",
                 datetime.now(timezone.utc).isoformat()))
            await self.bot.economy.db.commit()
            bid = cur.lastrowid
            em = discord.Embed(
                title="🎯 New Bounty!",
                description=f"**{target.display_name}** has a **{amount}** Scrap bounty!",
                color=0xE74C3C)
            em.add_field(name="Reason", value=reason or "No reason given", inline=False)
            em.add_field(name="Placed by", value=interaction.user.display_name, inline=True)
            em.add_field(name="Bounty ID", value=f"`{bid}`", inline=True)
            em.set_footer(text="Use /bounty claim to collect!")
            await interaction.followup.send(embed=em)

        elif action == "board":
            cur = await self.bot.economy.db.execute(
                """SELECT id, target_name, amount, reason, placer_name
                   FROM bounties WHERE guild_id = ? AND status = 'active'
                   ORDER BY amount DESC LIMIT 10""",
                (interaction.guild_id,))
            rows = await cur.fetchall()
            if not rows:
                await interaction.followup.send(
                    "📋 No active bounties. Use `/bounty place` to start one!",
                    ephemeral=True)
                return
            em = discord.Embed(title="🎯 Bounty Board", color=RUST_COLOR,
                               description="Active bounties — highest first")
            for bid, tname, amt, rsn, pname in rows:
                em.add_field(
                    name=f"#{bid} — {tname} ({amt} Scrap)",
                    value=f"_{rsn}_\nPlaced by {pname}",
                    inline=False)
            await interaction.followup.send(embed=em)

        elif action == "claim":
            if not bounty_id:
                await interaction.followup.send("❌ Give a bounty ID!", ephemeral=True)
                return
            cur = await self.bot.economy.db.execute(
                "SELECT target_id, target_name, amount, placer_id, status FROM bounties WHERE id = ? AND guild_id = ?",
                (bounty_id, interaction.guild_id))
            row = await cur.fetchone()
            if not row:
                await interaction.followup.send("❌ Bounty not found.", ephemeral=True)
                return
            tid, tname, amt, pid, status = row
            if status != "active":
                await interaction.followup.send("❌ Already claimed.", ephemeral=True)
                return
            if interaction.user.id == tid:
                await interaction.followup.send("❌ Can't claim your own bounty!", ephemeral=True)
                return
            # Mark claimed and pay
            await self.bot.economy.db.execute(
                "UPDATE bounties SET status = 'claimed' WHERE id = ?", (bounty_id,))
            await self.bot.economy.db.commit()
            await self.bot.economy.add_scrap(interaction.user.id, amt)
            em = discord.Embed(
                title="🎯 Bounty Claimed!",
                description=f"**{interaction.user.display_name}** collected **{amt}** Scrap\nfor {tname}!",
                color=GOLD)
            await interaction.followup.send(embed=em)

        elif action == "cancel":
            if not bounty_id:
                await interaction.followup.send("❌ Give a bounty ID!", ephemeral=True)
                return
            cur = await self.bot.economy.db.execute(
                "SELECT placer_id, amount, status FROM bounties WHERE id = ? AND guild_id = ?",
                (bounty_id, interaction.guild_id))
            row = await cur.fetchone()
            if not row:
                await interaction.followup.send("❌ Bounty not found.", ephemeral=True)
                return
            pid, amt, status = row
            if pid != interaction.user.id:
                await interaction.followup.send("❌ Only the placer can cancel.", ephemeral=True)
                return
            if status != "active":
                await interaction.followup.send("❌ Already claimed.", ephemeral=True)
                return
            await self.bot.economy.db.execute(
                "UPDATE bounties SET status = 'cancelled' WHERE id = ?", (bounty_id,))
            await self.bot.economy.db.commit()
            await self.bot.economy.add_scrap(interaction.user.id, amt)
            await interaction.followup.send(
                f"✅ Bounty #{bounty_id} cancelled. **{amt}** Scrap refunded.",
                ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Bounty(bot))
