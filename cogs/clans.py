"""Clan commands: /clan create, invite, accept, leave, kick, promote, info, leaderboard."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.clans import (
    ClanError,
    ClanService,
    CREATE_COST,
)


def _clans(bot: commands.Bot) -> ClanService:
    return bot.clans


def _economy(bot: commands.Bot):
    return bot.economy


class Clans(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    clan = app_commands.Group(name="clan", description="Clan management")

    async def _clan_embed(self, clan: dict) -> discord.Embed:
        clans = _clans(self.bot)
        members = await clans.get_members(clan["id"])
        econ = _economy(self.bot)
        total_scrap = await clans.clan_total_scrap(clan["id"], econ)

        role_emoji = {"leader": "👑", "officer": "🛡️", "member": "⚔️"}
        lines = []
        for m in members:
            emoji = role_emoji.get(m["role"], "⚔️")
            lines.append(f"{emoji} <@{m['user_id']}> — {m['role']}")

        embed = discord.Embed(
            title=f"🛡️ {clan['name']}",
            description="\n".join(lines) if lines else "No members.",
            color=0x6A1B9A,
        )
        embed.add_field(name="Members", value=str(len(members)), inline=True)
        embed.add_field(name="Total Scrap", value=f"{total_scrap:,}", inline=True)
        embed.add_field(name="Leader", value=f"<@{clan['leader_id']}>", inline=True)
        return embed

    @clan.command(name="create", description=f"Create a clan ({CREATE_COST} Scrap)")
    @app_commands.describe(name="Your clan's name")
    async def clan_create(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        clans = _clans(self.bot)
        econ = _economy(self.bot)
        try:
            # Charge first
            from services.economy import EconomyError
            try:
                await econ.deduct_scrap(interaction.user.id, CREATE_COST)
            except EconomyError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            clan = await clans.create_clan(interaction.user.id, name)
        except ClanError as exc:
            # Refund on failure
            await econ.add_scrap(interaction.user.id, CREATE_COST)
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        embed = await self._clan_embed(clan)
        embed.description = (
            f"🎉 Clan **{clan['name']}** created!\n\n" + (embed.description or "")
        )
        await interaction.followup.send(embed=embed)

    @clan.command(name="invite", description="Invite a player to your clan")
    @app_commands.describe(member="Who to invite")
    async def clan_invite(self, interaction: discord.Interaction,
                          member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        clans = _clans(self.bot)
        try:
            clan = await clans.invite(interaction.user.id, member.id)
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Invited {member.mention} to **{clan['name']}**!", ephemeral=True
        )
        # DM-ish: mention in followup is ephemeral, so also send a public note
        # (the invitee checks /clan invites)

    @clan.command(name="invites", description="Check your pending clan invites")
    async def clan_invites(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        clans = _clans(self.bot)
        invites = await clans.get_invites(interaction.user.id)
        if not invites:
            await interaction.followup.send(
                "📭 No pending clan invites.", ephemeral=True)
            return
        lines = [
            f"🛡️ **{i['clan_name']}** — invited by <@{i['invited_by']}>"
            for i in invites
        ]
        await interaction.followup.send(
            "📨 **Pending invites:**\n" + "\n".join(lines) +
            "\n\nUse `/clan accept` to join!",
            ephemeral=True)

    @clan.command(name="accept", description="Accept a clan invite")
    async def clan_accept(self, interaction: discord.Interaction):
        await interaction.response.defer()
        clans = _clans(self.bot)
        try:
            clan = await clans.accept_invite(interaction.user.id)
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        embed = await self._clan_embed(clan)
        await interaction.followup.send(
            f"🎉 {interaction.user.mention} joined **{clan['name']}**!",
            embed=embed)

    @clan.command(name="decline", description="Decline clan invites")
    async def clan_decline(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        clans = _clans(self.bot)
        try:
            await clans.decline_invite(interaction.user.id)
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("✅ Invites declined.", ephemeral=True)

    @clan.command(name="leave", description="Leave your clan")
    async def clan_leave(self, interaction: discord.Interaction):
        await interaction.response.defer()
        clans = _clans(self.bot)
        try:
            result = await clans.leave(interaction.user.id)
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if result.startswith("disbanded:"):
            name = result.split(":", 1)[1]
            await interaction.followup.send(
                f"💥 Clan **{name}** has been disbanded.")
        else:
            name = result.split(":", 1)[1]
            await interaction.followup.send(
                f"👋 {interaction.user.mention} left **{name}**.")

    @clan.command(name="kick", description="Kick a member from your clan")
    @app_commands.describe(member="Who to kick")
    async def clan_kick(self, interaction: discord.Interaction,
                        member: discord.Member):
        await interaction.response.defer()
        clans = _clans(self.bot)
        try:
            await clans.kick(interaction.user.id, member.id)
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"🥾 {member.mention} was kicked from the clan.")

    @clan.command(name="promote", description="Promote a member to officer")
    @app_commands.describe(member="Who to promote")
    async def clan_promote(self, interaction: discord.Interaction,
                           member: discord.Member):
        await interaction.response.defer()
        clans = _clans(self.bot)
        try:
            await clans.set_role(interaction.user.id, member.id, "officer")
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"🛡️ {member.mention} promoted to **Officer**!")

    @clan.command(name="transfer", description="Transfer leadership to another member")
    @app_commands.describe(member="Who becomes the new leader")
    async def clan_transfer(self, interaction: discord.Interaction,
                            member: discord.Member):
        await interaction.response.defer()
        clans = _clans(self.bot)
        try:
            await clans.set_role(interaction.user.id, member.id, "leader")
        except ClanError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"👑 {member.mention} is now the **Leader**!")

    @clan.command(name="info", description="Show your clan's info")
    async def clan_info(self, interaction: discord.Interaction):
        await interaction.response.defer()
        clans = _clans(self.bot)
        clan = await clans.get_user_clan(interaction.user.id)
        if not clan:
            await interaction.followup.send(
                "❌ You're not in a clan. Create one with `/clan create`!",
                ephemeral=True)
            return
        embed = await self._clan_embed(clan)
        await interaction.followup.send(embed=embed)

    @clan.command(name="leaderboard", description="Top clans by members")
    async def clan_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        clans = _clans(self.bot)
        econ = _economy(self.bot)
        top = await clans.leaderboard(10)
        if not top:
            await interaction.followup.send(
                "📭 No clans yet. Be the first with `/clan create`!")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, c in enumerate(top):
            medal = medals[i] if i < 3 else f"`{i + 1}.`"
            scrap = await clans.clan_total_scrap(c["id"], econ)
            lines.append(
                f"{medal} **{c['name']}** — {c['members']} members, "
                f"{scrap:,} Scrap")
        embed = discord.Embed(
            title="🏆 Clan Leaderboard",
            description="\n".join(lines),
            color=0xFFD700,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    # Init clan tables on the shared DB
    clans = ClanService(bot.economy.db)
    await clans.init()
    bot.clans = clans
    await bot.add_cog(Clans(bot))
