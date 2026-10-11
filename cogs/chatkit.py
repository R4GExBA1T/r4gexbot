"""In-game chat kit triggers: type the phrase in game chat, get the kit.

Listens to the Rust server's RCON feed for chat messages. When a player
types a kit's trigger phrase (set via /kit trigger), delivers that kit
via RCON with the kit's cooldown enforced per-player.

Runs as a background task; no-ops if RCON isn't configured.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks

log = logging.getLogger("chatkit")


class ChatKit(commands.Cog):
    """Background RCON chat listener for in-game kit claims."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (gamertag.lower(), kit_name) -> last claim datetime
        self._cooldowns: dict[tuple[str, str], datetime] = {}
        # trigger phrase (lower) -> (kit_name, contents, cooldown_hours)
        self._triggers: dict[str, tuple[str, str, float]] = {}

    async def cog_load(self) -> None:
        if self._rcon_configured():
            await self._load_triggers()
            self.chat_listener.start()
            self.refresh_triggers.start()
            log.info("ChatKit listener started")
        else:
            log.info("ChatKit: RCON not configured, listener disabled")

    async def cog_unload(self) -> None:
        self.chat_listener.cancel()
        self.refresh_triggers.cancel()

    def _rcon_configured(self) -> bool:
        return bool(os.getenv("RCON_HOST") and os.getenv("RCON_PORT")
                    and os.getenv("RCON_PASSWORD"))

    async def _load_triggers(self) -> None:
        """Load chat triggers from the kits table."""
        try:
            cur = await self.bot.economy.db.execute(
                "SELECT name, contents, cooldown_hours, chat_trigger FROM kits "
                "WHERE chat_trigger IS NOT NULL AND chat_trigger != ''")
            rows = await cur.fetchall()
            new_triggers = {}
            for name, contents, cd, trig in rows:
                new_triggers[trig.strip().lower()] = (name, contents, float(cd))
            self._triggers = new_triggers
            log.info(f"ChatKit: loaded {len(new_triggers)} chat triggers: "
                     f"{list(new_triggers.keys())}")
        except Exception as e:
            log.warning(f"ChatKit: failed to load triggers: {e}")

    @tasks.loop(minutes=2)
    async def refresh_triggers(self):
        """Pick up trigger changes without a restart."""
        await self._load_triggers()

    @tasks.loop(seconds=5)
    async def chat_listener(self):
        """Maintain RCON connection and listen for chat. Reconnects on drop."""
        if not self._rcon_configured():
            return
        try:
            import websockets
        except ImportError:
            return

        host = os.getenv("RCON_HOST")
        port = os.getenv("RCON_PORT")
        password = os.getenv("RCON_PASSWORD")
        uri = f"ws://{host}:{port}/{password}"

        try:
            async with websockets.connect(uri, open_timeout=10) as ws:
                log.info("ChatKit: RCON connected, listening for chat")
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await self._handle_message(data)
        except Exception as e:
            log.warning(f"ChatKit: RCON connection lost ({e}), retrying in 5s")
            await asyncio.sleep(5)

    async def _handle_message(self, data: dict) -> None:
        """Parse an incoming RCON message for kit trigger phrases."""
        message = data.get("Message", "")
        if not message or not self._triggers:
            return

        text = str(message)
        text_lower = text.lower()

        # Find which trigger phrase (if any) appears in this message
        matched = None
        for phrase in self._triggers:
            if phrase in text_lower:
                matched = phrase
                break
        if not matched:
            return

        log.info(f"ChatKit: trigger '{matched}' detected in: {text[:200]}")

        # Extract gamertag from common formats
        gamertag = None
        try:
            if "[CHAT]" in text:
                chat_part = text.split("[CHAT]", 1)[1].strip()
                if " : " in chat_part:
                    gamertag = chat_part.split(" : ", 1)[0].strip()
            elif ":" in text:
                potential = text.split(":", 1)[0].strip()
                for prefix in ["[SERVER]", "[RCON]"]:
                    potential = potential.replace(prefix, "").strip()
                if potential and len(potential) < 33:
                    gamertag = potential
        except (IndexError, ValueError):
            pass

        if not gamertag:
            log.warning(f"ChatKit: could not extract gamertag from: {text[:200]}")
            return

        gamertag = re.sub(r'\[.*?\]', '', gamertag).strip()
        if not gamertag:
            return

        kit_name, contents, cd_hours = self._triggers[matched]
        await self._try_give_kit(gamertag, kit_name, contents, cd_hours)

    async def _try_give_kit(self, gamertag: str, kit_name: str,
                            contents: str, cd_hours: float) -> None:
        """Check cooldown and deliver the kit via RCON."""
        key = (gamertag.lower(), kit_name)
        now = datetime.now(timezone.utc)
        last = self._cooldowns.get(key)
        cd = timedelta(hours=cd_hours)
        if last and (now - last) < cd:
            remaining = cd - (now - last)
            mins = int(remaining.total_seconds() // 60)
            hrs = mins // 60
            cd_msg = f"{hrs}h {mins % 60}m" if hrs else f"{mins}m"
            await self._rcon_say(
                f"{gamertag}, your {kit_name} kit is on cooldown ({cd_msg} left).")
            return

        from services import rcon as rcon_svc
        ok, msg = await rcon_svc.give_kit(gamertag, contents)
        if ok:
            self._cooldowns[key] = now
            await self._rcon_say(
                f"{gamertag} claimed the {kit_name} kit!")
            log.info(f"ChatKit: delivered {kit_name} kit to {gamertag}")
        else:
            log.warning(f"ChatKit: failed to deliver {kit_name} to {gamertag}: {msg}")

    async def _rcon_say(self, text: str) -> None:
        """Broadcast a message in game chat via RCON."""
        from services import rcon as rcon_svc
        safe = text.replace('"', "'")
        await rcon_svc.send_command(f'say "{safe}"')

    @discord.app_commands.command(name="rcon", description="🔧 Test RCON connection (admin)")
    async def rcon_test(self, interaction: discord.Interaction):
        """Admin-only: test if the bot can reach the game server via RCON."""
        await interaction.response.defer(ephemeral=True)
        if not (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id):
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        from services import rcon as rcon_svc
        if not rcon_svc.is_configured():
            await interaction.followup.send(
                "❌ RCON not configured (missing env vars).", ephemeral=True)
            return
        resp = await rcon_svc.send_command("server.hostname")
        if resp is None:
            await interaction.followup.send(
                "❌ RCON connection failed. Server may be offline or unreachable.",
                ephemeral=True)
        else:
            listener = "running" if self.chat_listener.is_running() else "stopped"
            trig_count = len(self._triggers)
            await interaction.followup.send(
                f"✅ RCON connected! Server: {resp[:100]}\n"
                f"Chat listener: {listener}\n"
                f"Active chat triggers: {trig_count}",
                ephemeral=True)

    @discord.app_commands.command(name="givetest", description="🔧 Test item delivery (admin)")
    async def give_test(self, interaction: discord.Interaction, gamertag: str):
        """Admin-only: try giving 1 bandage via RCON and show raw response."""
        await interaction.response.defer(ephemeral=True)
        if not (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id):
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        from services import rcon as rcon_svc
        # Try the give command and capture raw response
        resp = await rcon_svc.send_command(f'inventory.giveto "{gamertag}" "bandage" "1"')
        # Also check playerlist to verify name
        plist = await rcon_svc.send_command("global.playerlist")
        await interaction.followup.send(
            f"Give response: `{resp}`\n"
            f"Playerlist: `{plist[:500] if plist else 'None'}`",
            ephemeral=True)

    @discord.app_commands.command(name="chatdebug", description="🔧 Capture RCON chat for 30s (admin)")
    async def chat_debug(self, interaction: discord.Interaction):
        """Admin-only: listen to RCON for 30s and show what chat looks like."""
        await interaction.response.defer(ephemeral=True)
        if not (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id):
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        from services import rcon as rcon_svc
        if not rcon_svc.is_configured():
            await interaction.followup.send("❌ RCON not configured.", ephemeral=True)
            return
        await interaction.followup.send(
            "🎧 Listening to RCON for 30s... type in game chat or use the chat wheel NOW!",
            ephemeral=True)
        try:
            import websockets
            import json
            import asyncio
            host = os.getenv("RCON_HOST")
            port = os.getenv("RCON_PORT")
            password = os.getenv("RCON_PASSWORD")
            uri = f"ws://{host}:{port}/{password}"
            messages = []
            async with websockets.connect(uri, open_timeout=10) as ws:
                try:
                    async with asyncio.timeout(30):
                        async for raw in ws:
                            try:
                                data = json.loads(raw)
                                msg = str(data.get("Message", ""))[:200]
                                if msg:
                                    messages.append(msg)
                                    # Keep only last 20
                                    messages = messages[-20:]
                            except:
                                pass
                except asyncio.TimeoutError:
                    pass
            if messages:
                output = "\n".join(f"• `{m}`" for m in messages[-10:])
                await interaction.followup.send(
                    f"📨 Captured {len(messages)} messages:\n{output}",
                    ephemeral=True)
            else:
                await interaction.followup.send(
                    "📭 No messages received in 30s. RCON might not be pushing chat.",
                    ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatKit(bot))
