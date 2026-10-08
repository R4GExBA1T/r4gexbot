"""Support ticket system: /support open/close/add/remove.

Tickets are private channels visible only to the ticket creator and staff.
Staff = members with Manage Channels permission (or the server owner).
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C

# Ticket categories shown in the open dropdown.
TICKET_CATEGORIES = [
    app_commands.Choice(name="🎧 General", value="general"),
    app_commands.Choice(name="🚨 Report", value="report"),
    app_commands.Choice(name="🛒 Purchase", value="purchase"),
]

CATEGORY_LABELS = {
    "general": "🎧 General",
    "report": "🚨 Report",
    "purchase": "🛒 Purchase",
}

# Prefix for ticket channel names so we can identify them.
TICKET_PREFIX = "ticket-"


def _is_staff(member: discord.Member) -> bool:
    """Staff = manage_channels permission or server owner."""
    if member.guild.owner_id == member.id:
        return True
    return member.guild_permissions.manage_channels


def _is_ticket_channel(channel: discord.abc.GuildChannel) -> bool:
    return isinstance(channel, discord.TextChannel) and channel.name.startswith(TICKET_PREFIX)


class Support(app_commands.Group):
    """Ticket system for player support and ban appeals."""

    def __init__(self, bot: commands.Bot):
        super().__init__(name="support", description="🎫 Support tickets")
        self.bot = bot

    @app_commands.command(name="open", description="Open a support ticket")
    @app_commands.describe(
        category="What do you need help with?",
        reason="Briefly describe your issue",
    )
    @app_commands.choices(category=TICKET_CATEGORIES)
    async def ticket_open(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        reason: str,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        # Check if they already have an open ticket.
        existing = discord.utils.find(
            lambda c: _is_ticket_channel(c)
            and c.topic
            and f"Owner: {user.id}" in c.topic,
            guild.text_channels,
        )
        if existing:
            await interaction.followup.send(
                f"❌ You already have an open ticket: {existing.mention}",
                ephemeral=True,
            )
            return

        # Find or create the Tickets category.
        tickets_cat = discord.utils.find(
            lambda c: c.name.lower() == "tickets",
            guild.categories,
        )
        if tickets_cat is None:
            try:
                tickets_cat = await guild.create_category("🎫 TICKETS")
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ I need the **Manage Channels** permission to create ticket channels.",
                    ephemeral=True,
                )
                return

        # Channel visible only to the user, staff, and the bot.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_channels=True,
            ),
        }
        # Grant staff roles explicitly (any role with manage_channels).
        for role in guild.roles:
            if role.permissions.manage_channels and role != guild.default_role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True,
                )

        channel_name = f"{TICKET_PREFIX}{user.name.lower().replace(' ', '-')}-{user.discriminator if hasattr(user, 'discriminator') else user.id % 10000}"
        # Discord channel names: lowercase, no spaces, max 100 chars.
        channel_name = "".join(
            c if c.isalnum() or c == "-" else "-" for c in channel_name.lower()
        )[:90]

        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=tickets_cat,
                overwrites=overwrites,
                topic=f"Owner: {user.id} | Category: {category.value} | {reason[:100]}",
                reason=f"Ticket opened by {user} ({category.value})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create channels.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{CATEGORY_LABELS[category.value]}",
            description=(
                f"**Opened by:** {user.mention}\n"
                f"**Issue:** {reason}\n\n"
                f"Staff will be with you shortly. Please describe your issue in detail.\n"
                f"Use `/support close` to close this ticket when resolved."
            ),
            color=RUST_COLOR,
        )
        await channel.send(embed=embed)

        await interaction.followup.send(
            f"✅ Ticket created: {channel.mention}\n"
            f"Staff have been notified.",
            ephemeral=True,
        )

    @app_commands.command(name="close", description="Close the current ticket")
    @app_commands.describe(reason="Why is this ticket being closed? (optional)")
    async def ticket_close(
        self, interaction: discord.Interaction, reason: str = "No reason given"
    ):
        channel = interaction.channel
        if not _is_ticket_channel(channel):
            await interaction.response.send_message(
                "❌ This isn't a ticket channel.", ephemeral=True
            )
            return

        user = interaction.user
        # Only staff or the ticket owner can close.
        is_owner = channel.topic and f"Owner: {user.id}" in channel.topic
        if not (is_owner or _is_staff(user)):
            await interaction.response.send_message(
                "❌ Only staff or the ticket owner can close this ticket.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"🔒 Closing ticket... ({reason})"
        )
        # Give the message a moment to send, then delete.
        try:
            await channel.delete(reason=f"Ticket closed by {user}: {reason}")
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I need **Manage Channels** to close tickets.", ephemeral=True
            )

    @app_commands.command(name="add", description="Add someone to this ticket (staff only)")
    @app_commands.describe(user="The member to add to the ticket")
    async def ticket_add(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        channel = interaction.channel
        if not _is_ticket_channel(channel):
            await interaction.response.send_message(
                "❌ This isn't a ticket channel.", ephemeral=True
            )
            return
        if not _is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Only staff can add people to tickets.", ephemeral=True
            )
            return

        await channel.set_permissions(
            user,
            read_messages=True, send_messages=True,
            attach_files=True, embed_links=True,
        )
        await interaction.response.send_message(
            f"✅ {user.mention} added to the ticket."
        )

    @app_commands.command(name="remove", description="Remove someone from this ticket (staff only)")
    @app_commands.describe(user="The member to remove from the ticket")
    async def ticket_remove(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        channel = interaction.channel
        if not _is_ticket_channel(channel):
            await interaction.response.send_message(
                "❌ This isn't a ticket channel.", ephemeral=True
            )
            return
        if not _is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Only staff can remove people from tickets.", ephemeral=True
            )
            return

        # Don't let staff remove the ticket owner via this command.
        if channel.topic and f"Owner: {user.id}" in channel.topic:
            await interaction.response.send_message(
                "❌ You can't remove the ticket owner. Close the ticket instead.",
                ephemeral=True,
            )
            return

        await channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(
            f"✅ {user.mention} removed from the ticket."
        )


async def setup(bot: commands.Bot):
    bot.tree.add_command(Support(bot))
