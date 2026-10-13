"""ZORP — Zone of Raid Protection.

Player flow (in-game chat wheel):
  1. Player: "Can I build around here?" (wheel)
  2. Bot (in-game): "Are you stood in the centre of your base? Say YES to create your ZORP, or GOODBYE to remove it."
  3. Player: "Yes" (wheel) -> ZORP created at their current position.
     Player: "Goodbye" (wheel) -> their ZORP is deleted.
  4. Protection auto-toggles: building damage BLOCKED when offline,
     ALLOWED when online (purple ring always visible).

Mechanism: Rust Console native custom zones via RCON.
Position: server.printpos "<gamertag>" -> (x, y, z).
"""
import asyncio
import discord
import json
import logging
import os
import re
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands, tasks

from services import rcon

log = logging.getLogger("zorp")

# ZORP zone defaults
ZORP_RADIUS = 40  # meters
ZORP_COLOR = (128, 0, 128)  # purple


class Zorp(commands.Cog):
    """ZORP raid protection via native custom zones."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # gamertag.lower() -> True (waiting for yes/goodbye after prompt)
        self._pending: dict[str, datetime] = {}

    async def cog_load(self) -> None:
        await self._init_db()
        if self._rcon_configured():
            # Chat comes via ChatKit's RCON listener -> handle_chat()
            self.protection_poller.start()
            log.info("ZORP protection poller started")
        else:
            log.info("ZORP: RCON not configured, disabled")

    async def cog_unload(self) -> None:
        self.protection_poller.cancel()

    def _rcon_configured(self) -> bool:
        return bool(os.getenv("RCON_HOST") and os.getenv("RCON_PORT")
                    and os.getenv("RCON_PASSWORD"))

    async def _init_db(self) -> None:
        await self.bot.economy.db.execute("""
            CREATE TABLE IF NOT EXISTS zorps (
                gamertag TEXT PRIMARY KEY,
                zone_name TEXT NOT NULL,
                x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,
                radius REAL NOT NULL DEFAULT 40,
                created_at TEXT NOT NULL,
                protection_on INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT
            )
        """)
        # Add expires_at to existing tables
        try:
            await self.bot.economy.db.execute(
                "ALTER TABLE zorps ADD COLUMN expires_at TEXT")
        except Exception:
            pass  # Column already exists
        await self.bot.economy.db.commit()

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------
    async def get_position(self, gamertag: str) -> tuple[float, float, float] | None:
        """Get player's XYZ via server.printpos. Returns (x, y, z) or None."""
        try:
            resp = await rcon.send_command(f'server.printpos "{gamertag}"', timeout=10.0)
        except Exception as e:
            log.warning(f"ZORP: printpos failed for {gamertag}: {e}")
            return None
        if not resp:
            return None
        # Format: (-1265.62, 0.56, -1815.30)
        m = re.search(r'\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)', resp)
        if not m:
            log.warning(f"ZORP: could not parse position from: {resp[:100]}")
            return None
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)))

    # ------------------------------------------------------------------
    # Zone management
    # ------------------------------------------------------------------
    def _zone_name(self, gamertag: str) -> str:
        # Sanitize for zone name: alphanumeric + underscore
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', gamertag)
        return f"zorp_{safe}"

    async def create_zorp(self, gamertag: str) -> tuple[bool, str]:
        """Create a ZORP zone at the player's current position."""
        # Check if they already have one
        cur = await self.bot.economy.db.execute(
            "SELECT zone_name FROM zorps WHERE gamertag = ?", (gamertag.lower(),))
        if await cur.fetchone():
            return (False, "You already have a ZORP. Say GOODBYE to remove it first.")

        pos = await self.get_position(gamertag)
        if not pos:
            return (False, "Could not find your position. Try again.")
        x, y, z = pos
        zone = self._zone_name(gamertag)

        # Create the zone: sphere, PvP on, no building damage, building allowed
        # zones.createcustomzone "Name" (x,y,z) rotation Sphere radius pvp npc rad builddmg build
        create_cmd = (f'zones.createcustomzone "{zone}" '
                      f'({x:.2f},{y:.2f},{z:.2f}) 0 Sphere {ZORP_RADIUS} 1 1 0 0 1')
        try:
            await rcon.send_command(create_cmd, timeout=15.0)
        except Exception as e:
            log.warning(f"ZORP: create failed for {gamertag}: {e}")
            return (False, "Failed to create ZORP zone. Try again.")

        # Configure: purple ring, visible, enter/leave messages
        r, g, b = ZORP_COLOR
        edits = [
            ("showarea", "1"),
            ("color", f"({r},{g},{b})"),
            ("showchatmessage", "1"),
            ("entermessage", f"Entering \\\"{gamertag}'s\\\" ZORP"),
            ("leavemessage", f"Leaving \\\"{gamertag}'s\\\" ZORP"),
        ]
        for setting, value in edits:
            try:
                await rcon.send_command(
                    f'zones.editcustomzone "{zone}" {setting} "{value}"', timeout=10.0)
            except Exception as e:
                log.warning(f"ZORP: edit {setting} failed for {zone}: {e}")

        # Save to DB (protection starts ON — assume offline until poller confirms)
        # ZORP expires 24h after creation unless owner comes online (timer resets)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=24)
        await self.bot.economy.db.execute(
            """INSERT OR REPLACE INTO zorps
               (gamertag, zone_name, x, y, z, radius, created_at, protection_on, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (gamertag.lower(), zone, x, y, z, ZORP_RADIUS,
             now.isoformat(), expires.isoformat()))
        await self.bot.economy.db.commit()
        log.info(f"ZORP: created {zone} at ({x:.1f},{y:.1f},{z:.1f}) for {gamertag}, expires {expires.isoformat()}")
        return (True, f"ZORP created! Purple ring marks your protected zone ({ZORP_RADIUS}m). Protection activates when you log off. Expires in 24h unless you come online.")

    async def delete_zorp(self, gamertag: str) -> tuple[bool, str]:
        """Delete a player's ZORP zone."""
        cur = await self.bot.economy.db.execute(
            "SELECT zone_name FROM zorps WHERE gamertag = ?", (gamertag.lower(),))
        row = await cur.fetchone()
        if not row:
            return (False, "You don't have a ZORP to remove.")
        zone = row[0]
        try:
            resp = await rcon.send_command(
                f'zones.deletecustomzone "{zone}"', timeout=10.0)
            log.info(f"ZORP: delete RCON response for {zone}: {resp[:200] if resp else 'empty'}")
        except Exception as e:
            log.warning(f"ZORP: delete failed for {zone}: {e}")
            return (False, f"Failed to delete ZORP zone in-game: {e}. "
                           f"Zone kept in DB, try again.")
        # Verify deletion by listing zones
        try:
            zones_resp = await rcon.send_command("zones.listcustomzones", timeout=10.0)
            if zones_resp and zone in zones_resp:
                log.warning(f"ZORP: {zone} still in zones list after delete!")
                return (False, f"ZORP zone still exists in-game after delete. "
                               f"Not removing from DB.")
        except Exception as e:
            log.warning(f"ZORP: could not verify deletion for {zone}: {e}")
            # Continue anyway — don't block on verification failure
        await self.bot.economy.db.execute(
            "DELETE FROM zorps WHERE gamertag = ?", (gamertag.lower(),))
        await self.bot.economy.db.commit()
        log.info(f"ZORP: deleted {zone} for {gamertag}")
        return (True, "Your ZORP has been removed.")

    async def set_protection(self, gamertag: str, zone_name: str, on: bool) -> None:
        """Toggle building-damage protection (on = blocked when offline)."""
        value = "0" if on else "1"  # allowbuildingdamage 0 = no raid damage
        try:
            await rcon.send_command(
                f'zones.editcustomzone "{zone_name}" allowbuildingdamage {value}',
                timeout=10.0)
            await self.bot.economy.db.execute(
                "UPDATE zorps SET protection_on = ? WHERE gamertag = ?",
                (1 if on else 0, gamertag.lower(),))
            await self.bot.economy.db.commit()
            log.info(f"ZORP: protection {'ON' if on else 'OFF'} for {gamertag}")
        except Exception as e:
            log.warning(f"ZORP: protection toggle failed for {zone_name}: {e}")

    # ------------------------------------------------------------------
    # Chat wheel handling (called by ChatKit's RCON listener)
    # ------------------------------------------------------------------
    def _normalize_wheel(self, text: str) -> str:
        """Normalize wheel broadcast to a plain phrase."""
        tl = text.lower()
        # Rust Console chat-wheel localization keys (from live RCON capture)
        # "Can I build around here?" = Questions slot 1
        # "Yes" = Responses slot 0
        # "Goodbye" = Responses slot 6
        if "quick_chat_questions_slot_1" in tl:
            return "can i build around here?"
        if "quick_chat_responses_slot_0" in tl:
            return "yes"
        if "quick_chat_responses_slot_6" in tl:
            return "goodbye"
        # Plain-text fallback (typed chat)
        if "can i build" in tl or "build around here" in tl:
            return "can i build around here?"
        if re.search(r'\byes\b', tl):
            return "yes"
        if "goodbye" in tl or re.search(r'\bbye\b', tl):
            return "goodbye"
        return ""

    async def handle_chat(self, gamertag: str, text: str) -> None:
        """Handle a chat message from a player (called by ChatKit). Never throws."""
        try:
            phrase = self._normalize_wheel(text)
            if not phrase:
                return
            gt_lower = gamertag.lower()
            log.info(f"ZORP: phrase '{phrase}' from {gamertag}")

            if phrase == "can i build around here?":
                self._pending[gt_lower] = datetime.now(timezone.utc)
                try:
                    await rcon.send_command(
                        f'say "{gamertag}, are you stood in the centre of your base? '
                        f'Say YES on the chat wheel to create your ZORP, or GOODBYE to remove it."',
                        timeout=10.0)
                except Exception as e:
                    log.warning(f"ZORP: prompt failed: {e}")
                return

            if phrase == "yes":
                if gt_lower not in self._pending:
                    return
                del self._pending[gt_lower]
                try:
                    ok, msg = await self.create_zorp(gamertag)
                    await rcon.send_command(f'say "{gamertag}: {msg}"', timeout=10.0)
                except Exception as e:
                    log.warning(f"ZORP: create flow failed: {e}")
                return

            if phrase == "goodbye":
                if gt_lower in self._pending:
                    del self._pending[gt_lower]
                try:
                    ok, msg = await self.delete_zorp(gamertag)
                    if ok:
                        await rcon.send_command(f'say "{gamertag}: {msg}"', timeout=10.0)
                except Exception as e:
                    log.warning(f"ZORP: delete flow failed: {e}")
                return
        except Exception as e:
            log.warning(f"ZORP: handle_chat failed: {e}")

    # ------------------------------------------------------------------
    # Protection auto-toggle (online/offline)
    # ------------------------------------------------------------------
    @tasks.loop(minutes=5)
    async def protection_poller(self):
        """Every 5 min: protection ON for offline players, OFF for online.
        ZORP expires 24h after creation unless owner comes online (timer resets).
        """
        try:
            cur = await self.bot.economy.db.execute(
                "SELECT gamertag, zone_name, protection_on, expires_at FROM zorps")
            zorps = await cur.fetchall()
            if not zorps:
                return

            # Get online players
            online: set[str] = set()
            try:
                resp = await rcon.send_command("playerlist", timeout=15.0)
                if resp:
                    data = json.loads(resp)
                    for p in data:
                        name = p.get("DisplayName", "")
                        if name:
                            online.add(name.lower())
            except Exception as e:
                log.warning(f"ZORP: playerlist poll failed: {e}")
                return

            now = datetime.now(timezone.utc)
            for gamertag, zone_name, protection_on, expires_at in zorps:
                is_online = gamertag.lower() in online

                # If owner is online, reset the 24h expiration timer
                if is_online:
                    new_expires = now + timedelta(hours=24)
                    await self.bot.economy.db.execute(
                        "UPDATE zorps SET expires_at = ? WHERE gamertag = ?",
                        (new_expires.isoformat(), gamertag))
                    await self.bot.economy.db.commit()
                    log.debug(f"ZORP: {gamertag} online, expiration reset to {new_expires.isoformat()}")
                else:
                    # Owner offline: check if ZORP expired
                    if expires_at:
                        try:
                            exp = datetime.fromisoformat(expires_at)
                            if exp.tzinfo is None:
                                exp = exp.replace(tzinfo=timezone.utc)
                            if now >= exp:
                                log.info(f"ZORP: {gamertag}'s ZORP expired after 24h offline, deleting")
                                await self.delete_zorp(gamertag)
                                try:
                                    await rcon.send_command(
                                        f'say "{gamertag}\'s ZORP has expired after 24 hours."',
                                        timeout=10.0)
                                except Exception:
                                    pass
                                continue
                        except (ValueError, TypeError) as e:
                            log.warning(f"ZORP: bad expires_at for {gamertag}: {e}")

                # Protection ON when offline, OFF when online
                want_on = not is_online
                if bool(protection_on) != want_on:
                    await self.set_protection(gamertag, zone_name, want_on)
        except Exception as e:
            log.warning(f"ZORP: poller error: {e}")

    @protection_poller.before_loop
    async def _before_poller(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Admin commands
    # ------------------------------------------------------------------
    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="zorp", description="🛡️ Manage ZORP raid protection (admin)")
    @app_commands.describe(action="What to do",
                           player="Player gamertag (for create/delete)")
    @app_commands.choices(action=[
        app_commands.Choice(name="List all ZORPs", value="list"),
        app_commands.Choice(name="Delete a player's ZORP", value="delete"),
        app_commands.Choice(name="Debug: DB vs in-game zones", value="debug"),
    ])
    async def zorp(self, interaction: discord.Interaction,
                   action: str, player: str = ""):
        if not self._is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        if action == "list":
            cur = await self.bot.economy.db.execute(
                "SELECT gamertag, zone_name, x, y, z, protection_on, created_at FROM zorps")
            rows = await cur.fetchall()
            if not rows:
                await interaction.followup.send("No ZORPs active.", ephemeral=True)
                return
            lines = []
            for gt, zn, x, y, z, prot, created in rows:
                status = "🛡️ ON (offline)" if prot else "⚔️ OFF (online)"
                lines.append(f"**{gt}** → `{zn}` @ ({x:.0f},{z:.0f}) {status}")
            await interaction.followup.send("\n".join(lines), ephemeral=True)
        elif action == "delete":
            if not player:
                await interaction.followup.send("Provide a player gamertag.", ephemeral=True)
                return
            ok, msg = await self.delete_zorp(player)
            await interaction.followup.send(msg, ephemeral=True)
        elif action == "debug":
            # Show DB zorps vs in-game zones
            cur = await self.bot.economy.db.execute(
                "SELECT gamertag, zone_name FROM zorps")
            db_zorps = await cur.fetchall()
            try:
                zones_resp = await rcon.send_command(
                    "zones.listcustomzones", timeout=15.0)
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Failed to list in-game zones: {e}", ephemeral=True)
                return
            lines = [f"**DB ({len(db_zorps)}):**"]
            for gt, zn in db_zorps:
                lines.append(f"  {gt} → `{zn}`")
            lines.append(f"\n**In-game zones:**")
            lines.append(f"```{zones_resp[:1500] if zones_resp else '(empty)'}```")
            await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Zorp(bot))
