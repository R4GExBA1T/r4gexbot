"""Kits: claimable starter kits with cooldowns.

/kit list — see available kits
/kit claim <name> — claim a kit (cooldown enforced)
/kit create <name> <cooldown_hours> <contents> — admin creates a kit
/kit delete <name> — admin removes a kit

Discord-side now; RCON in-game delivery hooks in when server is linked.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta

RUST_COLOR = 0xCE6A2C


class Kits(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS kits (
                   name TEXT PRIMARY KEY,
                   contents TEXT,
                   cooldown_hours INTEGER,
                   created_by INTEGER,
                   chat_trigger TEXT)""")
        # Migrate: add chat_trigger column if the table predates it
        cur = await self.bot.economy.db.execute("PRAGMA table_info(kits)")
        cols = [row[1] for row in await cur.fetchall()]
        if "chat_trigger" not in cols:
            await self.bot.economy.db.execute(
                "ALTER TABLE kits ADD COLUMN chat_trigger TEXT")
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS kit_claims (
                   user_id INTEGER, kit_name TEXT,
                   claimed_at TEXT,
                   PRIMARY KEY (user_id, kit_name))""")
        await self.bot.economy.db.commit()
        # Seed/update the starter kit (the "I need wood" style auto-kit)
        # Preserve any existing chat_trigger on the starter kit
        cur = await self.bot.economy.db.execute(
            "SELECT chat_trigger FROM kits WHERE name = 'starter'")
        row = await cur.fetchone()
        starter_trigger = (row[0] if row and row[0] else "i need wood")
        await self.bot.economy.db.execute(
            """INSERT OR REPLACE INTO kits (name, contents, cooldown_hours, created_by, chat_trigger)
               VALUES (?, ?, ?, ?, ?)""",
            ("starter",
             "Eoka Pistol x1, Handmade Shells x5, Bandage x6, Stone Pickaxe x1, Stone Axe x1, Low Grade Fuel x50",
             0.5, 0, starter_trigger))
        # Seed the daily starter2 kit (24h cooldown, no chat trigger by default)
        cur = await self.bot.economy.db.execute(
            "SELECT chat_trigger FROM kits WHERE name = 'starter2'")
        row = await cur.fetchone()
        s2_trigger = (row[0] if row else None)
        # Only seed if it doesn't exist yet (don't overwrite Tyson's changes)
        if row is None:
            await self.bot.economy.db.execute(
                """INSERT INTO kits (name, contents, cooldown_hours, created_by, chat_trigger)
                   VALUES (?, ?, ?, ?, ?)""",
                ("starter2",
                 "Double Barrel Shotgun x1, Crossbow x1, Handmade Shells x12, Arrows x30, Stims x2, Bandage x6, Wood x6000, Stone x6000, Metal Frags x3000, Low Grade Fuel x100, Jackhammer x1, Chainsaw x1",
                 24, 0, None))
        # Seed metal frags kit for "I need metal" wheel trigger (daily)
        cur = await self.bot.economy.db.execute(
            "SELECT name FROM kits WHERE name = 'metal'")
        if await cur.fetchone() is None:
            await self.bot.economy.db.execute(
                """INSERT INTO kits (name, contents, cooldown_hours, created_by, chat_trigger)
                   VALUES (?, ?, ?, ?, ?)""",
                ("metal", "Metal Frags x3000", 24, 0, "need metal"))
        await self.bot.economy.db.commit()

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="kit", description="🎒 Claimable kits")
    @app_commands.describe(action="What to do",
                           name="Kit name",
                           cooldown_hours="Cooldown in hours (for create)",
                           contents="What's in the kit (for create)",
                           trigger="In-game chat phrase to trigger this kit (for trigger)")
    @app_commands.choices(action=[
        app_commands.Choice(name="List kits", value="list"),
        app_commands.Choice(name="Claim a kit", value="claim"),
        app_commands.Choice(name="Create kit (admin)", value="create"),
        app_commands.Choice(name="Delete kit (admin)", value="delete"),
        app_commands.Choice(name="Set chat trigger (admin)", value="trigger"),
    ])
    async def kit(self, interaction: discord.Interaction,
                  action: str, name: str = "",
                  cooldown_hours: int = 24, contents: str = "",
                  trigger: str = ""):
        await interaction.response.defer()

        if action == "list":
            cur = await self.bot.economy.db.execute(
                "SELECT name, contents, cooldown_hours, chat_trigger FROM kits ORDER BY name")
            rows = await cur.fetchall()
            if not rows:
                await interaction.followup.send("📦 No kits yet!", ephemeral=True)
                return
            em = discord.Embed(title="🎒 Available Kits", color=RUST_COLOR)
            for kname, kcontents, cd, trig in rows:
                # Check if user can claim (cooldown)
                cur2 = await self.bot.economy.db.execute(
                    "SELECT claimed_at FROM kit_claims WHERE user_id = ? AND kit_name = ?",
                    (interaction.user.id, kname))
                row2 = await cur2.fetchone()
                status = "✅ Ready"
                if row2:
                    claimed = datetime.fromisoformat(row2[0])
                    next_claim = claimed + timedelta(hours=cd)
                    if datetime.now(timezone.utc) < next_claim:
                        remaining = next_claim - datetime.now(timezone.utc)
                        hrs = int(remaining.total_seconds() // 3600)
                        mins = int((remaining.total_seconds() % 3600) // 60)
                        status = f"⏳ {hrs}h {mins}m"
                cd_display = f"{cd}h" if cd >= 1 else f"{int(cd * 60)}m"
                trig_line = f"\n💬 Chat: \"{trig}\"" if trig else ""
                em.add_field(
                    name=f"{kname} — {status}",
                    value=f"{kcontents}\n_Cooldown: {cd_display}_{trig_line}",
                    inline=False)
            em.set_footer(text="Use /kit claim <name> to claim!")
            await interaction.followup.send(embed=em)

        elif action == "claim":
            if not name:
                await interaction.followup.send("❌ Which kit? Use `/kit list` first.", ephemeral=True)
                return
            cur = await self.bot.economy.db.execute(
                "SELECT contents, cooldown_hours FROM kits WHERE name = ?", (name.lower(),))
            row = await cur.fetchone()
            if not row:
                await interaction.followup.send(f"❌ Kit `{name}` not found.", ephemeral=True)
                return
            contents, cd = row
            # Check cooldown
            cur = await self.bot.economy.db.execute(
                "SELECT claimed_at FROM kit_claims WHERE user_id = ? AND kit_name = ?",
                (interaction.user.id, name.lower()))
            row2 = await cur.fetchone()
            if row2:
                claimed = datetime.fromisoformat(row2[0])
                next_claim = claimed + timedelta(hours=cd)
                now = datetime.now(timezone.utc)
                if now < next_claim:
                    remaining = next_claim - now
                    hrs = int(remaining.total_seconds() // 3600)
                    mins = int((remaining.total_seconds() % 3600) // 60)
                    await interaction.followup.send(
                        f"⏳ On cooldown! Try again in {hrs}h {mins}m.", ephemeral=True)
                    return
            # Claim it
            await self.bot.economy.db.execute(
                """INSERT OR REPLACE INTO kit_claims (user_id, kit_name, claimed_at)
                   VALUES (?, ?, ?)""",
                (interaction.user.id, name.lower(), datetime.now(timezone.utc).isoformat()))
            await self.bot.economy.db.commit()

            # Try in-game RCON delivery
            from services import rcon as rcon_svc
            delivery_note = "In-game delivery coming when server is linked! For now, show this to an admin."
            if rcon_svc.is_configured():
                gamertag = await self.bot.economy.get_gamertag(interaction.user.id)
                if gamertag:
                    ok, msg = await rcon_svc.give_kit(gamertag, contents)
                    if ok:
                        delivery_note = f"✅ Delivered in-game to **{gamertag}**! Check your inventory."
                    else:
                        delivery_note = f"⚠️ In-game delivery failed ({msg}). Show this to an admin."
                else:
                    delivery_note = "⚠️ Link your gamertag with `/linkrust` for in-game delivery! For now, show this to an admin."

            em = discord.Embed(
                title=f"🎒 Kit Claimed: {name}",
                description=f"**Contents:**\n{contents}",
                color=0x57F287)
            em.set_footer(text=delivery_note)
            await interaction.followup.send(embed=em)

        elif action == "create":
            if not self._is_admin(interaction):
                await interaction.followup.send("❌ Admin only.", ephemeral=True)
                return
            if not name or not contents:
                await interaction.followup.send(
                    "❌ Give a name and contents! e.g. `/kit create name:starter cooldown_hours:24 contents:Wood x1000`",
                    ephemeral=True)
                return
            # Preserve existing chat_trigger if updating a kit
            cur = await self.bot.economy.db.execute(
                "SELECT chat_trigger FROM kits WHERE name = ?", (name.lower(),))
            row = await cur.fetchone()
            existing_trigger = row[0] if row else None
            await self.bot.economy.db.execute(
                "INSERT OR REPLACE INTO kits (name, contents, cooldown_hours, created_by, chat_trigger) VALUES (?, ?, ?, ?, ?)",
                (name.lower(), contents, max(1, cooldown_hours), interaction.user.id, existing_trigger))
            await self.bot.economy.db.commit()
            await interaction.followup.send(
                f"✅ Kit `{name}` created! ({cooldown_hours}h cooldown)", ephemeral=True)

        elif action == "delete":
            if not self._is_admin(interaction):
                await interaction.followup.send("❌ Admin only.", ephemeral=True)
                return
            if not name:
                await interaction.followup.send("❌ Which kit?", ephemeral=True)
                return
            await self.bot.economy.db.execute("DELETE FROM kits WHERE name = ?", (name.lower(),))
            await self.bot.economy.db.commit()
            await interaction.followup.send(f"✅ Kit `{name}` deleted.", ephemeral=True)

        elif action == "trigger":
            if not self._is_admin(interaction):
                await interaction.followup.send("❌ Admin only.", ephemeral=True)
                return
            if not name:
                await interaction.followup.send("❌ Which kit? e.g. `/kit action:Set chat trigger name:vip trigger:i need stone`", ephemeral=True)
                return
            cur = await self.bot.economy.db.execute(
                "SELECT name FROM kits WHERE name = ?", (name.lower(),))
            if not await cur.fetchone():
                await interaction.followup.send(f"❌ No kit named `{name}`.", ephemeral=True)
                return
            trig = trigger.strip().lower() if trigger else None
            await self.bot.economy.db.execute(
                "UPDATE kits SET chat_trigger = ? WHERE name = ?",
                (trig, name.lower()))
            await self.bot.economy.db.commit()
            if trig:
                await interaction.followup.send(
                    f"✅ Kit `{name}` now triggers when someone types **\"{trigger.strip()}\"** in game chat.",
                    ephemeral=True)
            else:
                await interaction.followup.send(
                    f"✅ Chat trigger removed from kit `{name}`.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Kits(bot))
