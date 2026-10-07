"""Heist command: /takeallr4gexba1tsmoneyandgiveittome — steal all of R4GExBA1T's Scrap."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

# Role required to use the heist command (created by staff)
HEIST_ROLE_NAME = "Heist Crew"
# R4GExBA1T's Discord username (the victim)
VICTIM_NAME = "r4gexba1t"


def _economy(bot: commands.Bot):
    return bot.economy


class Heist(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="takeallr4gexba1tsmoneyandgiveittome",
        description="💰 Steal ALL of R4GExBA1T's Scrap (Heist Crew only)",
    )
    async def heist(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Check for the Heist Crew role
        member = interaction.user
        has_role = any(
            r.name == HEIST_ROLE_NAME for r in getattr(member, "roles", [])
        )
        if not has_role:
            await interaction.followup.send(
                f"🚫 You need the **{HEIST_ROLE_NAME}** role to pull off this heist!",
            )
            return

        # Find R4GExBA1T in the guild
        guild = interaction.guild
        victim = None
        if guild:
            for m in guild.members:
                if m.name.lower() == VICTIM_NAME or m.display_name.lower() == VICTIM_NAME:
                    victim = m
                    break

        if victim is None:
            await interaction.followup.send(
                "🔍 R4GExBA1T isn't in this server — nothing to steal!",
            )
            return

        if victim.id == member.id:
            await interaction.followup.send(
                "🪞 You can't steal from yourself... nice try though.",
            )
            return

        economy = _economy(self.bot)
        victim_balance = await economy.get_balance(victim.id)

        if victim_balance <= 0:
            await interaction.followup.send(
                f"💸 {victim.display_name} is broke! Nothing to steal. 😭",
            )
            return

        # Take it all
        try:
            await economy.transfer(victim.id, member.id, victim_balance)
        except Exception as e:
            await interaction.followup.send(f"❌ Heist failed: {e}")
            return

        embed = discord.Embed(
            title="💰 HEIST SUCCESSFUL 💰",
            description=(
                f"{member.mention} just robbed **{victim.display_name}** blind!\n\n"
                f"**{victim_balance:,}** Scrap transferred! 🤑"
            ),
            color=0xFFD700,
        )
        embed.set_footer(text="R4GExBA1T has been officially robbed.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Heist(bot))
