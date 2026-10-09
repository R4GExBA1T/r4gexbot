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
                   created_by INTEGER)""")
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS kit_claims (
                   user_id INTEGER, kit_name TEXT,
                   claimed_at TEXT,
                   PRIMARY KEY (user_id, kit_name))""")
        await self.bot.economy.db.commit()
        # Seed a starter kit if none exist
        cur = await self.bot.economy.db.execute("SELECT COUNT(*) FROM kits")
        if (await cur.fetchone())[0] == 0:
            await self.bot.economy.db.execute(
                "INSERT INTO kits (name, contents, cooldown_hours, created_by) VALUES (?, ?, ?, ?)",
                ("starter", "Wood x1000, Stone x500, Basic tools", 24, 0))
            await self.bot.economy.db.commit()

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="kit", description="🎒 Claimable kits")
    @app_commands.describe(action="What to do",
                           name="Kit name",
                           cooldown_hours="Cooldown in hours (for create)",
                           contents="What's in the kit (for create)")
    @app_commands.choices(action=[
        app_commands.Choice(name="List kits", value="list"),
        app_commands.Choice(name="Claim a kit", value="claim"),
        app_commands.Choice(name="Create kit (admin)", value="create"),
        app_commands.Choice(name="Delete kit (admin)", value="delete"),
    ])
    async def kit(self, interaction: discord.Interaction,
                  action: str, name: str = "",
                  cooldown_hours: int = 24, contents: str = ""):
        await interaction.response.defer()

        if action == "list":
            cur = await self.bot.economy.db.execute(
                "SELECT name, contents, cooldown_hours FROM kits ORDER BY name")
            rows = await cur.fetchall()
            if not rows:
                await interaction.followup.send("📦 No kits yet!", ephemeral=True)
                return
            em = discord.Embed(title="🎒 Available Kits", color=RUST_COLOR)
            for kname, kcontents, cd in rows:
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
                em.add_field(
                    name=f"{kname} — {status}",
                    value=f"{kcontents}\n_Cooldown: {cd}h_",
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
            em = discord.Embed(
                title=f"🎒 Kit Claimed: {name}",
                description=f"**Contents:**\n{contents}",
                color=0x57F287)
            em.set_footer(text="In-game delivery coming when server is linked! For now, show this to an admin.")
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
            await self.bot.economy.db.execute(
                "INSERT OR REPLACE INTO kits (name, contents, cooldown_hours, created_by) VALUES (?, ?, ?, ?)",
                (name.lower(), contents, max(1, cooldown_hours), interaction.user.id))
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Kits(bot))
