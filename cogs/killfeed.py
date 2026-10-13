"""Killfeed, K/D tracking, kill Scrap rewards, raid protection, stat cards.

Listens to the Rust server's RCON feed for death/join/leave messages.
- Posts PvP kills live to the configured killfeed Discord channel.
- Tracks kills/deaths/streaks per gamertag, pays Scrap per PvP kill.
- Tracks raid protection for new players (time-based, shown on stat cards).
- /killfeed shows recent kills + K/D leaderboard.
- /stats renders a player stat card image.
- /protect shows raid protection status.

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
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("killfeed")

# Killers that are NPCs/environment, not players
NPC_KILLERS = (
    "bear", "wolf", "boar", "chicken", "horse", "stag", "shark",
    "scientist", "patrol helicopter", "attack helicopter", "bradley",
    "apc", "turret",
)
# No Scrap if the same killer downs the same victim within this window
ANTI_FARM_MINUTES = 10

DEATH_PVP = re.compile(r"^(.+?)\s+was killed by\s+(.+?)$", re.IGNORECASE)
DEATH_SUICIDE = re.compile(r"^(.+?)\s+committed suicide", re.IGNORECASE)
DEATH_DIED = re.compile(r"^(.+?)\s+died\b", re.IGNORECASE)
JOIN_RE = re.compile(r"^(.+?)\s+joined\b", re.IGNORECASE)
LEFT_RE = re.compile(r"^(.+?)\s+(left|disconnected)\b", re.IGNORECASE)
ID_SUFFIX = re.compile(r"\[\d+\]\s*$")


def clean_name(raw: str) -> str:
    name = ID_SUFFIX.sub("", raw).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def is_npc(killer: str) -> bool:
    kl = killer.lower()
    return any(npc in kl for npc in NPC_KILLERS)


class Killfeed(commands.Cog):
    """RCON killfeed + combat stats."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # gamertag.lower() -> join datetime (for playtime)
        self._sessions: dict[str, datetime] = {}

    async def cog_load(self) -> None:
        db = self.bot.economy.db
        await db.execute(
            """CREATE TABLE IF NOT EXISTS player_stats (
                   gamertag TEXT PRIMARY KEY,
                   kills INTEGER DEFAULT 0,
                   deaths INTEGER DEFAULT 0,
                   kill_scrap INTEGER DEFAULT 0,
                   pending_scrap INTEGER DEFAULT 0,
                   best_streak INTEGER DEFAULT 0,
                   current_streak INTEGER DEFAULT 0,
                   first_seen TEXT,
                   playtime_seconds INTEGER DEFAULT 0)""")
        await db.execute(
            """CREATE TABLE IF NOT EXISTS kill_log (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   killer TEXT, victim TEXT, ts TEXT, is_pvp INTEGER)""")
        await db.commit()
        if self._rcon_configured():
            self.kill_listener.start()
            log.info("Killfeed listener started")
        else:
            log.info("Killfeed: RCON not configured, listener disabled")

    async def cog_unload(self) -> None:
        self.kill_listener.cancel()

    def _rcon_configured(self) -> bool:
        return bool(os.getenv("RCON_HOST") and os.getenv("RCON_PORT")
                    and os.getenv("RCON_PASSWORD"))

    # -- config helpers (read guild_config directly, no cog ordering issues) --
    async def _cfg(self, guild_id: int, key: str, default: str) -> str:
        cur = await self.bot.economy.db.execute(
            "SELECT value FROM guild_config WHERE guild_id = ? AND key = ?",
            (guild_id, key))
        row = await cur.fetchone()
        return row[0] if row else default

    async def _cfg_int(self, guild_id: int, key: str, default: int) -> int:
        try:
            return int(await self._cfg(guild_id, key, str(default)))
        except (ValueError, TypeError):
            return default

    # -- RCON listener -------------------------------------------------------
    @tasks.loop(seconds=5)
    async def kill_listener(self):
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
                log.info("Killfeed: RCON connected, listening for deaths")
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await self._handle_message(data)
        except Exception as e:
            log.warning(f"Killfeed: RCON connection lost ({e}), retrying in 5s")
            await asyncio.sleep(5)

    async def _handle_message(self, data: dict) -> None:
        message = data.get("Message", "")
        if not message:
            return
        text = str(message).strip()

        m = DEATH_PVP.match(text)
        if m:
            await self._on_death(clean_name(m.group(1)), clean_name(m.group(2)))
            return
        m = DEATH_SUICIDE.match(text)
        if m:
            await self._on_suicide(clean_name(m.group(1)))
            return
        m = DEATH_DIED.match(text)
        if m:
            await self._on_env_death(clean_name(m.group(1)))
            return
        m = JOIN_RE.match(text)
        if m:
            await self._on_join(clean_name(m.group(1)))
            return
        m = LEFT_RE.match(text)
        if m:
            await self._on_leave(clean_name(m.group(1)))
            return

    # -- stat helpers --------------------------------------------------------
    async def _ensure_stats(self, gamertag: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.bot.economy.db.execute(
            "INSERT OR IGNORE INTO player_stats (gamertag, first_seen) VALUES (?, ?)",
            (gamertag, now))
        await self.bot.economy.db.commit()

    async def _get_stats(self, gamertag: str) -> dict | None:
        await self._ensure_stats(gamertag)
        cur = await self.bot.economy.db.execute(
            "SELECT kills, deaths, kill_scrap, pending_scrap, best_streak,"
            " current_streak, first_seen, playtime_seconds"
            " FROM player_stats WHERE gamertag = ?", (gamertag,))
        row = await cur.fetchone()
        if not row:
            return None
        return {
            "kills": row[0], "deaths": row[1], "kill_scrap": row[2],
            "pending_scrap": row[3], "best_streak": row[4],
            "current_streak": row[5], "first_seen": row[6],
            "playtime_seconds": row[7],
        }

    async def _discord_id_for(self, gamertag: str) -> int | None:
        cur = await self.bot.economy.db.execute(
            "SELECT discord_id FROM links WHERE LOWER(gamertag) = LOWER(?)",
            (gamertag,))
        row = await cur.fetchone()
        return int(row[0]) if row else None

    # -- event handlers ------------------------------------------------------
    async def _on_death(self, victim: str, killer: str) -> None:
        """Someone was killed by someone/something."""
        if not victim:
            return
        now = datetime.now(timezone.utc)
        await self._ensure_stats(victim)
        db = self.bot.economy.db

        if is_npc(killer) or not killer:
            # Environmental death
            await db.execute(
                "UPDATE player_stats SET deaths = deaths + 1,"
                " current_streak = 0 WHERE gamertag = ?", (victim,))
            await db.execute(
                "INSERT INTO kill_log (killer, victim, ts, is_pvp)"
                " VALUES (?, ?, ?, 0)", (killer or "environment", victim,
                                         now.isoformat()))
            await db.commit()
            log.info(f"Killfeed: {victim} died to {killer or 'environment'}")
            return

        if is_npc(victim) and killer and not is_npc(killer):
            # Player killed an NPC (scientist) — 20 Scrap reward, no K/D change
            await self._ensure_stats(killer)
            try:
                npc_scrap = 20
                await db.execute(
                    "UPDATE player_stats SET kill_scrap = kill_scrap + ?"
                    " WHERE gamertag = ?", (npc_scrap, killer.lower()))
                await db.commit()
                # Bank the Scrap if linked
                from services.economy import EconomyService
                # Find linked Discord user for the killer
                cur = await db.execute(
                    "SELECT discord_id FROM links WHERE gamertag = ?",
                    (killer.lower(),))
                row = await cur.fetchone()
                if row:
                    econ = self.bot.economy
                    await econ.add_scrap(row[0], npc_scrap)
                log.info(f"Killfeed: {killer} killed NPC {victim} (+{npc_scrap} Scrap)")
            except Exception as e:
                log.warning(f"Killfeed: NPC kill reward failed: {e}")
            return

        if killer.lower() == victim.lower():
            await self._on_suicide(victim)
            return

        # Victim's streak before it gets wiped (for "streak ended" callouts)
        vstats = await self._get_stats(victim)
        victim_streak = (vstats or {}).get("current_streak", 0)

        # PvP kill
        await self._ensure_stats(killer)
        await db.execute(
            "UPDATE player_stats SET kills = kills + 1, current_streak = current_streak + 1,"
            " best_streak = MAX(best_streak, current_streak + 1)"
            " WHERE gamertag = ?", (killer,))
        await db.execute(
            "UPDATE player_stats SET deaths = deaths + 1, current_streak = 0"
            " WHERE gamertag = ?", (victim,))
        await db.execute(
            "INSERT INTO kill_log (killer, victim, ts, is_pvp)"
            " VALUES (?, ?, ?, 1)", (killer, victim, now.isoformat()))
        await db.commit()
        log.info(f"Killfeed: {killer} killed {victim}")

        # Scrap reward (with anti-farm)
        awarded = await self._award_kill_scrap(killer, victim, now)
        # Post a rich embed to killfeed channels
        kstats = await self._get_stats(killer)
        embed = self._build_kill_embed(killer, victim, kstats,
                                         victim_streak, awarded, now)
        await self._post_killfeed(embed)

    async def _on_suicide(self, victim: str) -> None:
        if not victim:
            return
        db = self.bot.economy.db
        await self._ensure_stats(victim)
        await db.execute(
            "UPDATE player_stats SET deaths = deaths + 1, current_streak = 0"
            " WHERE gamertag = ?", (victim,))
        await db.execute(
            "INSERT INTO kill_log (killer, victim, ts, is_pvp)"
            " VALUES (?, ?, ?, 0)",
            (victim, victim, datetime.now(timezone.utc).isoformat()))
        await db.commit()

    async def _on_env_death(self, victim: str) -> None:
        await self._on_death(victim, "environment")

    async def _on_join(self, gamertag: str) -> None:
        if not gamertag:
            return
        await self._ensure_stats(gamertag)
        self._sessions[gamertag.lower()] = datetime.now(timezone.utc)

    async def _on_leave(self, gamertag: str) -> None:
        if not gamertag:
            return
        start = self._sessions.pop(gamertag.lower(), None)
        if start:
            secs = int((datetime.now(timezone.utc) - start).total_seconds())
            if secs > 0:
                await self.bot.economy.db.execute(
                    "UPDATE player_stats SET playtime_seconds = playtime_seconds + ?"
                    " WHERE gamertag = ?", (secs, gamertag))
                await self.bot.economy.db.commit()

    async def _award_kill_scrap(self, killer: str, victim: str,
                                now: datetime) -> int:
        """Pay Scrap for a PvP kill, with anti-farm protection.

        Returns the amount actually awarded (0 if anti-farm blocked it).
        """
        # Anti-farm: same killer -> same victim within window = no Scrap
        cutoff = (now - timedelta(minutes=ANTI_FARM_MINUTES)).isoformat()
        cur = await self.bot.economy.db.execute(
            "SELECT COUNT(*) FROM kill_log WHERE killer = ? AND victim = ?"
            " AND is_pvp = 1 AND ts > ? AND ts < ?",
            (killer, victim, cutoff, now.isoformat()))
        row = await cur.fetchone()
        if row and row[0] > 0:
            log.info(f"Killfeed: anti-farm blocked Scrap for {killer} -> {victim}")
            return 0

        # Find a guild with kill rewards enabled to get the amount
        amount = 10
        for guild in self.bot.guilds:
            amount = await self._cfg_int(guild.id, "kill_scrap", 50)
            if amount > 0:
                break
        if amount <= 0:
            return 0

        db = self.bot.economy.db
        discord_id = await self._discord_id_for(killer)
        if discord_id:
            try:
                await self.bot.economy.add_scrap(discord_id, amount)
                await db.execute(
                    "UPDATE player_stats SET kill_scrap = kill_scrap + ?"
                    " WHERE gamertag = ?", (amount, killer))
                log.info(f"Killfeed: +{amount} Scrap to {killer} (discord {discord_id})")
            except Exception as e:
                log.warning(f"Killfeed: failed to pay {killer}: {e}")
                return 0
        else:
            # Bank it until they link with /linkrust
            await db.execute(
                "UPDATE player_stats SET pending_scrap = pending_scrap + ?"
                " WHERE gamertag = ?", (amount, killer))
            log.info(f"Killfeed: banked +{amount} Scrap for unlinked {killer}")
        await db.commit()
        return amount

    @staticmethod
    def _streak_callout(streak: int) -> str | None:
        if streak >= 10:
            return "👑 **UNSTOPPABLE** — double-digit kill streak!"
        if streak >= 7:
            return "☠️ **ON A TEAR** — 7-kill streak!"
        if streak >= 5:
            return "⚡ **RAMPAGE** — 5-kill streak!"
        if streak >= 3:
            return "🔥 Heating up — 3-kill streak"
        return None

    def _build_kill_embed(self, killer: str, victim: str,
                          kstats: dict | None, victim_streak: int,
                          awarded: int, now: datetime) -> discord.Embed:
        """The live killfeed post — built to pop."""
        kills = (kstats or {}).get("kills", 0)
        deaths = (kstats or {}).get("deaths", 0)
        streak = (kstats or {}).get("current_streak", 0)
        kd = (kills / deaths) if deaths else float(kills)

        # Colour escalates with the killer's streak
        if streak >= 10:
            color = 0xFF0000
        elif streak >= 5:
            color = 0xFF6B00
        else:
            color = 0x8B00FF  # R4GE purple

        # Coloured banner: killer's name PURPLE, victim's name RED.
        # Discord has no per-word text colour in embeds, so the names ride
        # in an ANSI code block (35 = magenta/purple, 31 = red).
        def _ansi(name: str, code: str) -> str:
            safe = name.replace("`", "'")
            return f"\u001b[1;{code}m{safe}\u001b[0m"

        banner = (f"```ansi\n{_ansi(killer, '35')}  ⚔️  "
                  f"{_ansi(victim, '31')}\n```")
        lines = ["💀 **ELIMINATED**", banner]
        callout = self._streak_callout(streak)
        if callout:
            lines.append(callout)
        if victim_streak >= 3:
            lines.append(
                f"💥 Ended **{victim}**'s {victim_streak}-kill streak!")

        em = discord.Embed(description="\n".join(lines), color=color,
                           timestamp=now)
        killer_line = f"{kills}K / {deaths}D • {kd:.2f} K/D"
        if streak >= 2:
            killer_line += f" • 🔥 {streak} streak"
        em.add_field(name="🎯 Killer", value=killer_line, inline=True)
        if awarded > 0:
            em.add_field(name="🪙 Reward", value=f"+{awarded} Scrap",
                         inline=True)
        em.set_footer(text=f"R4GE 3X — Kill #{kills}")
        return em

    async def _post_killfeed(self, embed: discord.Embed) -> None:
        for guild in self.bot.guilds:
            ch_id = await self._cfg_int(guild.id, "killfeed_channel", 0)
            ch = guild.get_channel(ch_id) if ch_id else None
            if ch is None:
                # No channel configured — fall back to a #killfeed channel
                # so the feed works out of the box (/config still overrides)
                ch = discord.utils.get(guild.text_channels, name="killfeed")
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception as e:
                    log.warning(f"Killfeed: failed to post: {e}")

    async def pay_pending_scrap(self, gamertag: str, discord_id: int) -> int:
        """Pay out banked kill Scrap when a player links. Returns amount paid."""
        stats = await self._get_stats(gamertag)
        pending = (stats or {}).get("pending_scrap", 0)
        if pending and pending > 0:
            await self.bot.economy.add_scrap(discord_id, pending)
            db = self.bot.economy.db
            await db.execute(
                "UPDATE player_stats SET pending_scrap = 0,"
                " kill_scrap = kill_scrap + ? WHERE gamertag = ?",
                (pending, gamertag))
            await db.commit()
        return pending

    # -- commands ------------------------------------------------------------
    @app_commands.command(name="killfeed", description="⚔️ Recent kills + K/D leaderboard")
    async def killfeed_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        db = self.bot.economy.db
        em = discord.Embed(title="⚔️ Killfeed", color=0x8B00FF)

        cur = await db.execute(
            "SELECT killer, victim, ts FROM kill_log WHERE is_pvp = 1"
            " ORDER BY id DESC LIMIT 8")
        rows = await cur.fetchall()
        if rows:
            lines = []
            for killer, victim, ts in rows:
                try:
                    t = datetime.fromisoformat(ts)
                    ago = datetime.now(timezone.utc) - t
                    mins = int(ago.total_seconds() // 60)
                    when = f"{mins}m ago" if mins >= 1 else "just now"
                except Exception:
                    when = ""
                lines.append(f"💀 **{killer}** → **{victim}** ({when})")
            em.add_field(name="Recent kills", value="\n".join(lines), inline=False)
        else:
            em.add_field(name="Recent kills",
                         value="No kills tracked yet. Go touch grass. (In-game.)",
                         inline=False)

        cur = await db.execute(
            "SELECT gamertag, kills, deaths FROM player_stats"
            " WHERE kills > 0 ORDER BY kills DESC LIMIT 10")
        rows = await cur.fetchall()
        if rows:
            lines = []
            for i, (gt, k, d) in enumerate(rows, 1):
                kd = (k / d) if d else float(k)
                lines.append(f"**{i}.** {gt} — {k}K/{d}D ({kd:.2f} K/D)")
            em.add_field(name="🏆 Top killers", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=em)

    @app_commands.command(name="stats", description="📊 Player stat card")
    @app_commands.describe(gamertag="In-game name (defaults to your linked gamertag)")
    async def stats_cmd(self, interaction: discord.Interaction,
                        gamertag: str | None = None):
        await interaction.response.defer()
        if not gamertag:
            gamertag = await self.bot.economy.get_gamertag(interaction.user.id)
            if not gamertag:
                await interaction.followup.send(
                    "Link your gamertag first with `/linkrust`, or pass a name: `/stats gamertag:SomePlayer`")
                return
        stats = await self._get_stats(gamertag)
        if not stats or (stats["kills"] == 0 and stats["deaths"] == 0):
            await interaction.followup.send(
                f"No combat data for **{gamertag}** yet.")
            return

        prot = await self._protection_text(gamertag, interaction.guild_id)
        try:
            from services import statcard as sc
            path = sc.render(
                gamertag=gamertag,
                kills=stats["kills"], deaths=stats["deaths"],
                best_streak=stats["best_streak"],
                scrap_earned=stats["kill_scrap"],
                playtime_seconds=stats["playtime_seconds"],
                protection_text=prot)
            await interaction.followup.send(
                file=discord.File(path, filename="stats.png"))
        except Exception as e:
            log.warning(f"Killfeed: stat card render failed: {e}")
            kd = (stats["kills"] / stats["deaths"]
                  if stats["deaths"] else float(stats["kills"]))
            await interaction.followup.send(
                f"📊 **{gamertag}** — {stats['kills']}K/{stats['deaths']}D"
                f" ({kd:.2f} K/D) | Best streak {stats['best_streak']}"
                f" | +{stats['kill_scrap']} Scrap from kills")

    async def _protection_text(self, gamertag: str, guild_id: int | None) -> str:
        """Human-readable raid protection status."""
        if not guild_id:
            return ""
        hours = await self._cfg_int(guild_id, "raidprotect_hours", 24)
        if hours <= 0:
            return ""
        stats = await self._get_stats(gamertag)
        first = stats.get("first_seen") if stats else None
        if not first:
            return ""
        try:
            first_dt = datetime.fromisoformat(first)
        except Exception:
            return ""
        ends = first_dt + timedelta(hours=hours)
        now = datetime.now(timezone.utc)
        if now < ends:
            left = ends - now
            h = int(left.total_seconds() // 3600)
            m = int((left.total_seconds() % 3600) // 60)
            return f"🛡️ Protected {h}h {m}m left"
        return "⚔️ No protection"

    @app_commands.command(name="protect", description="🛡️ Check raid protection status")
    @app_commands.describe(gamertag="In-game name (defaults to your linked gamertag)")
    async def protect_cmd(self, interaction: discord.Interaction,
                          gamertag: str | None = None):
        await interaction.response.defer(ephemeral=True)
        if not gamertag:
            gamertag = await self.bot.economy.get_gamertag(interaction.user.id)
            if not gamertag:
                await interaction.followup.send(
                    "Link your gamertag first with `/linkrust`, or pass a name.",
                    ephemeral=True)
                return
        text = await self._protection_text(gamertag, interaction.guild_id)
        if not text:
            await interaction.followup.send(
                f"**{gamertag}**: no raid protection active.", ephemeral=True)
        else:
            await interaction.followup.send(
                f"**{gamertag}**: {text}\n"
                f"_Protection is time-based — raiding a protected player breaks server rules._",
                ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Killfeed(bot))
