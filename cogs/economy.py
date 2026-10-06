"""Economy commands: /daily, /weekly, /balance, /leaderboard, /give,
/linkrust, /unlinkrust.

All balance logic goes through services.economy.EconomyService — this cog
only handles Discord I/O and friendly messages.
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from services.economy import (
    EconomyError,
    EconomyService,
)

RUST_COLOR = 0xCE6A2C  # rusty orange
VIP_ROLE_NAME = "VIP"
STAFF_ROLE_NAMES = {"Owner", "Admin"}

# Bandit Camp wheel: segments + the color each tier lands on.
WHEEL_SEGMENTS = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚫", "⚪"]
TIER_WHEEL_COLOR = {"jackpot": "🟡", "rare": "🟣", "uncommon": "🔵", "common": "⚪"}


def _economy(bot: commands.Bot) -> EconomyService:
    return bot.economy  # attached in bot.py setup_hook


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _err(self, interaction: discord.Interaction, exc: EconomyError):
        await interaction.followup.send(str(exc), ephemeral=True)

    async def _bandit_spin(self, interaction: discord.Interaction, result_embed: discord.Embed, tier: str):
        """Bandit Camp wheel animation: spins the wheel in-chat, slowing down
        until it lands on the result tier, then swaps in the result embed."""
        segs = WHEEL_SEGMENTS.copy()

        def wheel_text():
            return f"**🎡 Spinning the wheel...**\n⬇️\n{' '.join(segs)}"

        msg = await interaction.followup.send(wheel_text(), wait=True)
        spins = 14
        try:
            for i in range(spins):
                # Ease-out: fast at first, slower as it settles.
                await asyncio.sleep(0.12 + (i / spins) ** 2 * 0.55)
                segs = [segs[-1]] + segs[:-1]
                await msg.edit(content=wheel_text())
            # Land the pointer on the tier's color.
            target = TIER_WHEEL_COLOR.get(tier, "⚪")
            while segs[0] != target:
                segs = [segs[-1]] + segs[:-1]
            await msg.edit(content=wheel_text())
            await asyncio.sleep(0.6)
        except (discord.NotFound, discord.HTTPException):
            pass  # message gone or rate-limited; just show the result
        await msg.edit(content=None, embed=result_embed)

    # -- daily wheel ----------------------------------------------------

    @app_commands.command(name="daily", description="Spin the daily wheel for Scrap (once every 24h)")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            result = await _economy(self.bot).claim_daily(interaction.user.id)
        except EconomyError as exc:
            await self._err(interaction, exc)
            return

        tier_lines = {
            "jackpot": "🎰 **JACKPOT!!** The wheel screams your name!",
            "rare": "💎 **RARE!** Big scrap haul!",
            "uncommon": "⭐ **Nice spin!** Solid scrap.",
            "common": "🎡 The wheel turns...",
        }
        embed = discord.Embed(
            title="🎡 Daily Wheel Spin",
            description=tier_lines[result.tier],
            color=RUST_COLOR,
        )
        embed.add_field(name="Won", value=f"**{result.total}** Scrap", inline=True)
        if result.bonus_pct:
            embed.add_field(
                name="Streak bonus",
                value=f"+{result.bonus_pct}% ({result.streak}-day streak 🔥)",
                inline=True,
            )
        else:
            embed.add_field(name="Streak", value=f"{result.streak}-day 🔥", inline=True)
        embed.add_field(name="Balance", value=f"**{result.new_balance}** Scrap", inline=False)
        embed.set_footer(text=f"Spin again in 24h • {interaction.user.display_name}")
        await self._bandit_spin(interaction, embed, result.tier)

    # -- VIP hourly spin --------------------------------------------------

    @app_commands.command(name="vipspin", description="VIP perk: spin the wheel every hour")
    async def vipspin(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not any(r.name == VIP_ROLE_NAME for r in interaction.user.roles):
            await interaction.followup.send(
                f"👑 `/vipspin` is a **{VIP_ROLE_NAME}** perk — one free wheel spin every hour.",
                ephemeral=True,
            )
            return
        try:
            result = await _economy(self.bot).claim_vip_spin(interaction.user.id)
        except EconomyError as exc:
            await self._err(interaction, exc)
            return

        tier_lines = {
            "jackpot": "🎰 **JACKPOT!!** The wheel screams your name!",
            "rare": "💎 **RARE!** Big scrap haul!",
            "uncommon": "⭐ **Nice spin!** Solid scrap.",
            "common": "🎡 The wheel turns...",
        }
        embed = discord.Embed(
            title="👑 VIP Hourly Spin",
            description=tier_lines[result.tier],
            color=0xFFD700,  # gold
        )
        embed.add_field(name="Won", value=f"**{result.total}** Scrap", inline=True)
        embed.add_field(name="Balance", value=f"**{result.new_balance}** Scrap", inline=True)
        embed.set_footer(text=f"Spin again in 1h • {interaction.user.display_name}")
        await self._bandit_spin(interaction, embed, result.tier)

    # -- weekly ----------------------------------------------------------

    @app_commands.command(name="weekly", description="Claim your weekly Scrap stash (once every 7 days)")
    async def weekly(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            result = await _economy(self.bot).claim_weekly(interaction.user.id)
        except EconomyError as exc:
            await self._err(interaction, exc)
            return

        embed = discord.Embed(
            title="📦 Weekly Scrap Drop",
            description="The supply drop lands at your feet.",
            color=RUST_COLOR,
        )
        embed.add_field(name="Received", value=f"**{result.total}** Scrap", inline=True)
        if result.bonus_pct:
            embed.add_field(name="Streak bonus", value=f"+{result.bonus_pct}% 🔥", inline=True)
        embed.add_field(name="Balance", value=f"**{result.new_balance}** Scrap", inline=False)
        await interaction.followup.send(embed=embed)

    # -- balance ----------------------------------------------------------

    @app_commands.command(name="balance", description="Check your Scrap balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bal = await _economy(self.bot).get_balance(interaction.user.id)
        embed = discord.Embed(
            title=f"💰 {interaction.user.display_name}'s Scrap",
            description=f"**{bal}** Scrap",
            color=RUST_COLOR,
        )
        await interaction.followup.send(embed=embed)

    # -- leaderboard ------------------------------------------------------

    @app_commands.command(name="leaderboard", description="Top 10 richest Scrap holders")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await _economy(self.bot).get_leaderboard(10)
        if not rows:
            await interaction.followup.send(
                "Nobody has any Scrap yet. Be the first to spin `/daily`!", ephemeral=True
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, bal) in enumerate(rows, start=1):
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            name = member.display_name if member else f"<@{user_id}>"
            prefix = medals[i - 1] if i <= 3 else f"`{i}.`"
            lines.append(f"{prefix} **{name}** — {bal} Scrap")

        embed = discord.Embed(
            title="🏆 Scrap Leaderboard",
            description="\n".join(lines),
            color=RUST_COLOR,
        )
        await interaction.followup.send(embed=embed)

    # -- give -------------------------------------------------------------

    @app_commands.command(name="give", description="Send Scrap to another member")
    @app_commands.describe(member="Who gets the Scrap", amount="How much Scrap to send")
    async def give(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        await interaction.response.defer()
        try:
            sender_bal, _ = await _economy(self.bot).transfer(
                interaction.user.id, member.id, amount
            )
        except EconomyError as exc:
            await self._err(interaction, exc)
            return

        await interaction.followup.send(
            f"💸 {interaction.user.mention} sent **{amount}** Scrap to {member.mention}! "
            f"(You have {sender_bal} left)"
        )

    # -- ecogive (staff only) -----------------------------------------------

    @app_commands.command(name="ecogive", description="Staff only: grant Scrap to a member (creates it)")
    @app_commands.describe(member="Who gets the Scrap", amount="How much Scrap to grant")
    async def ecogive(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        await interaction.response.defer(ephemeral=True)
        if not any(r.name in STAFF_ROLE_NAMES for r in interaction.user.roles):
            await interaction.followup.send(
                "🔒 `/ecogive` is staff-only.", ephemeral=True
            )
            return
        if amount <= 0:
            await interaction.followup.send("❌ Amount must be positive.", ephemeral=True)
            return
        new_bal = await _economy(self.bot).add_scrap(member.id, amount)
        await interaction.followup.send(
            f"🎁 {interaction.user.mention} granted **{amount}** Scrap to {member.mention} "
            f"(now at **{new_bal}**).",
            ephemeral=True,
        )

    # -- reset (staff only) ---------------------------------------------------

    @app_commands.command(name="reset", description="Staff only: reset a player's spin/reward cooldown")
    @app_commands.describe(member="Whose timer to reset", timer="Which timer to reset")
    @app_commands.choices(timer=[
        app_commands.Choice(name="🎡 Daily Wheel", value="daily"),
        app_commands.Choice(name="👑 VIP Spin", value="vip"),
        app_commands.Choice(name="📦 Weekly Reward", value="weekly"),
    ])
    async def reset(self, interaction: discord.Interaction, member: discord.Member, timer: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if not any(r.name in STAFF_ROLE_NAMES for r in interaction.user.roles):
            await interaction.followup.send("🔒 `/reset` is staff-only.", ephemeral=True)
            return
        await _economy(self.bot).reset_timer(member.id, timer.value)
        await interaction.followup.send(
            f"🔄 {interaction.user.mention} reset {member.mention}'s **{timer.name}** cooldown — "
            f"they can spin again now.",
            ephemeral=True,
        )

    # -- Rust Console gamertag linking (for future server rewards) --------

    @app_commands.command(name="linkrust", description="Link your Rust Console gamertag for future server rewards")
    @app_commands.describe(gamertag="Your Xbox gamertag or PlayStation ID")
    async def linkrust(self, interaction: discord.Interaction, gamertag: str):
        await interaction.response.defer(ephemeral=True)
        gamertag = gamertag.strip()
        if not (2 <= len(gamertag) <= 32):
            await interaction.followup.send(
                "❌ That doesn't look like a gamertag — it should be 2–32 characters.",
                ephemeral=True,
            )
            return
        await _economy(self.bot).link_rust(interaction.user.id, gamertag)
        await interaction.followup.send(
            f"🔗 Rust Console gamertag linked (`{gamertag}`). You'll be ready when "
            "server rewards go live.",
            ephemeral=True,
        )

    @app_commands.command(name="unlinkrust", description="Unlink your Rust Console gamertag")
    async def unlinkrust(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        removed = await _economy(self.bot).unlink_rust(interaction.user.id)
        await interaction.followup.send(
            "🔓 Gamertag unlinked." if removed else "You don't have a gamertag linked.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
