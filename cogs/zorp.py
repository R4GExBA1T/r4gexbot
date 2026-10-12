"""ZORP — Zone of Raid Protection.

Player flow (in-game chat wheel):
  1. Player opens chat wheel -> "Can I build around here?"
  2. Bot asks in chat: "Are you stood in the centre of your base?"
  3. Player answers via wheel: "Yes" -> ZORP created at their position.
     "Goodbye" -> their ZORP is deleted.
  4. Zone auto-enables when they log off, disables when they log on.

Mechanism: Rust Console native custom zones with building damage OFF.
"""
import discord
from discord import app_commands
from discord.ext import commands

from services import rcon


class Zorp(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="zorpdebug", description="🛡️ Probe ZORP RCON commands (admin)")
    async def zorpdebug(self, interaction: discord.Interaction):
        """Test whether zone + position commands work via RCON."""
        if not self._is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        lines = []
        for label, cmd in [
            ("zones.listcustomzones", "zones.listcustomzones"),
            ("server.playerlistpos", "server.playerlistpos"),
            ("location", "location"),
        ]:
            try:
                resp = await rcon.send_command(cmd, timeout=12.0)
                preview = (resp or "<empty response>")[:600]
                lines.append(f"**{label}** → OK\n```{preview}```")
            except Exception as e:
                lines.append(f"**{label}** → ERROR: {e}")
        await interaction.followup.send("\n\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Zorp(bot))
