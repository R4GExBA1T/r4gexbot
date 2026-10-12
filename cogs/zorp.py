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
        """Test whether zone + position commands work via RCON.

        Captures both the direct command response AND broadcast output,
        since some commands print to the console stream instead.
        """
        if not self._is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        lines = []

        # 1. Zone list (direct response already proven to work)
        try:
            resp = await rcon.send_command("zones.listcustomzones", timeout=12.0)
            preview = (resp or "<empty response>")[:300]
            lines.append(f"**zones.listcustomzones** → OK\n```{preview}```")
        except Exception as e:
            lines.append(f"**zones.listcustomzones** → ERROR: {e}")

        # 2. Position commands: capture direct response + 8s of broadcast
        for cmd in ["server.playerlistpos", "players", "status"]:
            direct = await rcon.send_command(cmd, timeout=10.0)
            broadcast = await self._capture_broadcast(cmd, seconds=8)
            d_prev = (direct or "<empty>")[:300]
            b_prev = (broadcast or "<nothing in broadcast>")[:800]
            lines.append(f"**{cmd}** direct → ```{d_prev}```\n"
                         f"**{cmd}** broadcast → ```{b_prev}```")

        # 3. Find available commands mentioning position/team/zone
        for filt in ["playerlistpos", "position", "team", "zone"]:
            resp = await rcon.send_command(f"find {filt}", timeout=10.0)
            preview = (resp or "<empty>")[:500]
            lines.append(f"**find {filt}** → ```{preview}```")

        await interaction.followup.send("\n\n".join(lines), ephemeral=True)

    async def _capture_broadcast(self, command: str, seconds: int = 8) -> str:
        """Send a command on a fresh socket and collect everything for N seconds."""
        import asyncio, json, os
        try:
            import websockets
        except ImportError:
            return "<no websockets>"
        host = os.getenv("RCON_HOST")
        port = os.getenv("RCON_PORT")
        password = os.getenv("RCON_PASSWORD")
        if not (host and port and password):
            return "<RCON not configured>"
        uri = f"ws://{host}:{port}/{password}"
        collected = []
        try:
            async with websockets.connect(uri, open_timeout=10) as ws:
                await ws.send(json.dumps({
                    "Identifier": 1, "Message": command, "Name": "WebRcon"}))
                end = asyncio.get_event_loop().time() + seconds
                while True:
                    remaining = end - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                        data = json.loads(raw)
                        msg = str(data.get("Message", "")).strip()
                        if msg and msg not in collected:
                            collected.append(msg)
                    except asyncio.TimeoutError:
                        break
        except Exception as e:
            return f"<error: {e}>"
        return "\n".join(collected)


async def setup(bot: commands.Bot):
    await bot.add_cog(Zorp(bot))
