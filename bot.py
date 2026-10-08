"""Ximmy — Rust-themed Discord casino bot.

Slash commands only. The token is read from the DISCORD_TOKEN environment
variable (see .env.example). Slash commands are synced on startup via
setup_hook.
"""

from __future__ import annotations

import os
import ssl as ssl_module
import sys

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

from services.economy import EconomyService

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PROXY = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "ximmy.db")


def _make_connector() -> aiohttp.TCPConnector:
    # Cloudflare (in front of Discord's gateway) terminates websocket
    # upgrades when the TLS handshake advertises ALPN, so use a context
    # that offers no ALPN protocols at all. Plain HTTPS API calls are
    # unaffected.
    ctx = ssl_module.create_default_context()
    return aiohttp.TCPConnector(ssl=ctx)


class Ximmy(commands.Bot):
    def __init__(self, proxy: str | None = None) -> None:
        intents = discord.Intents.default()  # no privileged intents needed
        kwargs: dict = {"command_prefix": "!", "intents": intents}
        if proxy:
            kwargs["proxy"] = proxy  # route through egress proxy when required
        super().__init__(**kwargs)
        self.economy = EconomyService(DB_PATH)

    async def _async_setup_hook(self) -> None:
        await super()._async_setup_hook()
        # Install the no-ALPN connector before the HTTP session is created
        # in static_login (the event loop is running here).
        self.http.connector = _make_connector()

    async def setup_hook(self) -> None:
        # Connect the economy DB first so cogs can use it immediately.
        await self.economy.connect()
        await self.load_extension("cogs.economy")
        await self.load_extension("cogs.casino")
        await self.load_extension("cogs.clans")
        await self.load_extension("cogs.store")
        await self.load_extension("cogs.heist")
        # NOTE: Auto-sync disabled — commands are managed manually via API.
        # The safe auto-sync (copy_global_to + empty-payload guard) works
        # correctly and was used to register /clan on 2026-10-07. It can be
        # re-enabled by uncommenting the block below.
        #
        # Safe auto-sync block (guarded against the 2026-10-07 wipe):
        # DISABLED again 2026-10-08 after registering /gamble
        # guild = discord.Object(id=1556869956388266037)  # R4GE 3X
        # self.tree.copy_global_to(guild=guild)
        # payload = list(self.tree.walk_commands(guild=guild))
        # if not payload:
        #     print("Ximmy online — REFUSED guild sync: empty payload, skipping to avoid wipe.")
        # else:
        #     synced = await self.tree.sync(guild=guild)
        #     print(f"Ximmy online — synced {len(synced)} slash commands.")
        print(f"Ximmy online — auto-sync disabled, commands managed via API.")

    async def close(self) -> None:
        await self.economy.close()
        await super().close()


def main() -> None:
    if not TOKEN:
        sys.exit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and paste "
            "your bot token, or export DISCORD_TOKEN in your shell."
        )
    bot = Ximmy(proxy=PROXY)
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
