"""In-game chat kit trigger: type the phrase in game chat, get the starter kit.

Listens to the Rust server's RCON feed for chat messages. When a player
types the trigger phrase (default: "i need wood"), delivers the starter
kit via RCON with a 30-minute per-player cooldown.

Runs as a background task; no-ops if RCON isn't configured.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks

log = logging.getLogger("chatkit")

TRIGGER_PHRASE = "i need wood"
COOLDOWN_MINUTES = 30
# Kit contents must match the "starter" kit in cogs/kits.py
KIT_CONTENTS = "Eoka Pistol x1, Handmade Shells x5, Bandage x6, Stone Pickaxe x1, Stone Axe x1, Low Grade Fuel x50"


class ChatKit(commands.Cog):
    """Background RCON chat listener for in-game kit claims."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldowns: dict[str, datetime] = {}  # gamertag.lower() -> last claim

    async def cog_load(self) -> None:
        if self._rcon_configured():
            self.chat_listener.start()
            log.info("ChatKit listener started")
        else:
            log.info("ChatKit: RCON not configured, listener disabled")

    async def cog_unload(self) -> None:
        self.chat_listener.cancel()

    def _rcon_configured(self) -> bool:
        return bool(os.getenv("RCON_HOST") and os.getenv("RCON_PORT")
                    and os.getenv("RCON_PASSWORD"))

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
        """Parse an incoming RCON message for chat triggers."""
        message = data.get("Message", "")
        if not message:
            return

        # Rust RCON chat messages come through with
        # "[CHAT] Gamertag : message" format in the Message field
        text = str(message)
        if "[chat]" not in text.lower():
            return

        # Extract gamertag and chat text: "[CHAT] Name : hello"
        try:
            chat_part = text.split("[CHAT]", 1)[1].strip()
            if " : " not in chat_part:
                return
            gamertag, chat_text = chat_part.split(" : ", 1)
            gamertag = gamertag.strip()
            chat_text = chat_text.strip().lower()
        except (IndexError, ValueError):
            return

        if TRIGGER_PHRASE not in chat_text:
            return

        await self._try_give_kit(gamertag)

    async def _try_give_kit(self, gamertag: str) -> None:
        """Check cooldown and deliver the kit via RCON."""
        key = gamertag.lower()
        now = datetime.now(timezone.utc)
        last = self._cooldowns.get(key)
        if last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES):
            remaining = timedelta(minutes=COOLDOWN_MINUTES) - (now - last)
            mins = int(remaining.total_seconds() // 60)
            await self._rcon_say(
                f"{gamertag}, your kit is on cooldown ({mins}m left).")
            return

        from services import rcon as rcon_svc
        ok, msg = await rcon_svc.give_kit(gamertag, KIT_CONTENTS)
        if ok:
            self._cooldowns[key] = now
            await self._rcon_say(
                f"{gamertag} claimed the starter kit! Type '{TRIGGER_PHRASE}' in chat for yours (30m cooldown).")
            log.info(f"ChatKit: delivered starter kit to {gamertag}")
        else:
            log.warning(f"ChatKit: failed to deliver kit to {gamertag}: {msg}")

    async def _rcon_say(self, text: str) -> None:
        """Broadcast a message in game chat via RCON."""
        from services import rcon as rcon_svc
        safe = text.replace('"', "'")
        await rcon_svc.send_command(f'say "{safe}"')


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatKit(bot))
