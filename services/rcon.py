"""WebRCON client for the Rust Console game server.

Connects to the server's RCON websocket to run in-game commands,
e.g. inv.giveplayer for kit delivery.

Credentials come from Railway env vars: RCON_HOST, RCON_PORT, RCON_PASSWORD.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

log = logging.getLogger("rcon")

try:
    import websockets
    _HAS_WS = True
except ImportError:
    _HAS_WS = False


def is_configured() -> bool:
    """True if all RCON env vars are present."""
    return bool(os.getenv("RCON_HOST") and os.getenv("RCON_PORT")
                and os.getenv("RCON_PASSWORD"))


async def send_command(command: str, timeout: float = 10.0) -> str | None:
    """Send a single RCON command, return the server's response text.

    Returns None if RCON isn't configured or the send failed.
    """
    if not _HAS_WS:
        log.warning("websockets package not installed; RCON unavailable")
        return None
    if not is_configured():
        return None

    host = os.getenv("RCON_HOST")
    port = os.getenv("RCON_PORT")
    password = os.getenv("RCON_PASSWORD")
    uri = f"ws://{host}:{port}/{password}"

    try:
        async with websockets.connect(uri, open_timeout=timeout) as ws:
            msg = json.dumps({
                "Identifier": 1,
                "Message": command,
                "Name": "WebRcon",
            })
            await ws.send(msg)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(raw)
                return data.get("Message", "")
            except asyncio.TimeoutError:
                return ""
    except Exception as e:
        log.warning(f"RCON command failed: {e}")
        return None


# Common Rust item shortnames for kit parsing
ITEM_ALIASES = {
    "wood": "wood",
    "stone": "stones",
    "stones": "stones",
    "metal": "metal.fragments",
    "metal fragments": "metal.fragments",
    "scrap": "scrap",
    "cloth": "cloth",
    "leather": "leather",
    "paper": "paper",
    "rope": "rope",
    "fat": "fat.animal",
    "bone": "bone.fragments",
    "charcoal": "charcoal",
    "gunpowder": "gunpowder",
    "sulfur": "sulfur",
    "sulfur ore": "sulfur.ore",
    "metal ore": "metal.ore",
    "hqm": "metal.refined",
    "high quality metal": "metal.refined",
    "low grade fuel": "lowgradefuel",
    "crude oil": "crude.oil",
    # tools / weapons
    "rock": "rock",
    "torch": "torch",
    "hatchet": "hatchet",
    "pickaxe": "pickaxe",
    "bow": "bow.hunting",
    "arrow": "arrow.wooden",
    "pistol": "pistol.semiauto",
    "revolver": "pistol.revolver",
    "shotgun": "shotgun.double",
    "ak": "rifle.ak",
    "ak47": "rifle.ak",
    "lr": "rifle.lr300",
    "mp5": "smg.mp5",
    "thompson": "smg.thompson",
    "custom": "smg.custom",
    # ammo
    "5.56": "ammo.rifle",
    "556": "ammo.rifle",
    "9mm": "ammo.pistol",
    "buckshot": "ammo.shotgun",
    "slug": "ammo.shotgun.slug",
    # medical / food
    "bandage": "bandage",
    "medsyringe": "syringe.medical",
    "syringe": "syringe.medical",
    # building
    "building plan": "building.planner",
    "hammer": "hammer",
    "tool cupboard": "cupboard.tool",
    "tc": "cupboard.tool",
    "sleeping bag": "sleepingbag",
    "bed": "bed",
}


def parse_kit_contents(contents: str) -> list[tuple[str, int]]:
    """Parse a kit contents string like 'Wood x1000, Stone x500' into
    [(item_shortname, amount), ...]. Unknown items are skipped.
    """
    items: list[tuple[str, int]] = []
    for part in contents.split(","):
        part = part.strip()
        if not part:
            continue
        # Split "Wood x1000" into name and amount
        if " x" in part.lower():
            idx = part.lower().rfind(" x")
            name = part[:idx].strip().lower()
            try:
                amount = int(part[idx + 2:].strip().replace(",", ""))
            except ValueError:
                amount = 1
        else:
            name = part.strip().lower()
            amount = 1
        shortname = ITEM_ALIASES.get(name)
        if shortname:
            items.append((shortname, max(1, amount)))
        else:
            log.warning(f"Unknown kit item, skipping: {name}")
    return items


async def give_kit(gamertag: str, contents: str) -> tuple[bool, str]:
    """Deliver a kit's items to a player via RCON inv.giveplayer.

    Returns (success, message).
    """
    items = parse_kit_contents(contents)
    if not items:
        return False, "No deliverable items found in kit."

    delivered = 0
    for shortname, amount in items:
        # inv.giveplayer splits large stacks; chunk at 1000
        remaining = amount
        while remaining > 0:
            chunk = min(remaining, 1000)
            resp = await send_command(
                f'inv.giveplayer "{gamertag}" {shortname} {chunk}')
            if resp is None:
                return False, "RCON connection failed."
            delivered += 1
            remaining -= chunk

    return True, f"Delivered {len(items)} item types to {gamertag}."
