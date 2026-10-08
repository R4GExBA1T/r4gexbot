"""Server configuration: admins can customize the bot per-server.

/config view — see all current settings
/config set <key> <value> — change a setting
/config reset — restore defaults
"""
import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C

# Setting definitions: key -> (description, type, default)
SETTINGS = {
    # Roles
    "vip_role": ("Name of the VIP role (for /vipspin)", "role_name", "VIP"),
    "staff_role": ("Name of the staff role (for tickets, giveaways)", "role_name", "Staff"),
    "thief_role": ("Name of the heist role", "role_name", "Thief Princess👑"),
    # Economy
    "daily_min": ("Daily wheel minimum prize", "int", "10"),
    "daily_max": ("Daily wheel maximum common prize", "int", "50"),
    "daily_jackpot": ("Daily wheel jackpot", "int", "1000"),
    "daily_cooldown_hours": ("Hours between daily spins", "int", "24"),
    "vip_min": ("VIP wheel minimum prize", "int", "5"),
    "vip_max": ("VIP wheel maximum common prize", "int", "20"),
    "vip_jackpot": ("VIP wheel jackpot", "int", "300"),
    "vip_cooldown_hours": ("Hours between VIP spins", "int", "1"),
    "starting_scrap": ("Scrap new users start with", "int", "100"),
    # Casino
    "min_bet": ("Minimum bet for casino games", "int", "10"),
    "max_bet": ("Maximum bet for casino games (0 = no limit)", "int", "0"),
    "hilo_multiplier": ("Hi-Lo multiplier per correct guess (x100, e.g. 140 = 1.4x)", "int", "140"),
    "clan_cost": ("Scrap cost to create a clan", "int", "50"),
    # Channels
    "welcome_channel": ("Channel ID for welcome messages (0 = disabled)", "int", "0"),
    "log_channel": ("Channel ID for mod logs (0 = disabled)", "int", "0"),
}


class Config(commands.Cog):
    """Admin configuration for the bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS guild_config (
                   guild_id INTEGER, key TEXT, value TEXT,
                   PRIMARY KEY (guild_id, key))""")
        await self.bot.economy.db.commit()

    async def get(self, guild_id: int, key: str) -> str:
        """Get a setting value, falling back to default."""
        cur = await self.bot.economy.db.execute(
            "SELECT value FROM guild_config WHERE guild_id = ? AND key = ?",
            (guild_id, key))
        row = await cur.fetchone()
        if row:
            return row[0]
        return SETTINGS[key][2]

    async def get_int(self, guild_id: int, key: str) -> int:
        return int(await self.get(guild_id, key))

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="config", description="⚙️ Configure the bot (admin only)")
    @app_commands.describe(action="What to do",
                           setting="Which setting (for set)",
                           value="New value (for set)")
    @app_commands.choices(action=[
        app_commands.Choice(name="View all settings", value="view"),
        app_commands.Choice(name="Set a setting", value="set"),
        app_commands.Choice(name="Reset to defaults", value="reset"),
    ])
    async def config(self, interaction: discord.Interaction,
                     action: str, setting: str = "", value: str = ""):
        await interaction.response.defer(ephemeral=True)

        if not self._is_admin(interaction):
            await interaction.followup.send(
                "❌ Admin only.", ephemeral=True)
            return

        guild_id = interaction.guild_id

        if action == "view":
            em = discord.Embed(title="⚙️ Server Configuration", color=RUST_COLOR)
            # Group by category
            groups = {"Roles": [], "Economy": [], "Casino": [], "Channels": []}
            for key, (desc, typ, default) in SETTINGS.items():
                val = await self.get(guild_id, key)
                if key.endswith("_role"):
                    groups["Roles"].append(f"`{key}`: {val}\n└ {desc}")
                elif key in ("daily_min", "daily_max", "daily_jackpot", "daily_cooldown_hours",
                             "vip_min", "vip_max", "vip_jackpot", "vip_cooldown_hours",
                             "starting_scrap"):
                    groups["Economy"].append(f"`{key}`: {val}\n└ {desc}")
                elif key in ("min_bet", "max_bet", "hilo_multiplier", "clan_cost"):
                    groups["Casino"].append(f"`{key}`: {val}\n└ {desc}")
                else:
                    groups["Channels"].append(f"`{key}`: {val}\n└ {desc}")
            for gname, items in groups.items():
                if items:
                    em.add_field(name=gname, value="\n".join(items), inline=False)
            em.set_footer(text="Use /config set <setting> <value> to change one.")
            await interaction.followup.send(embed=em, ephemeral=True)

        elif action == "set":
            if setting not in SETTINGS:
                valid = ", ".join(f"`{k}`" for k in SETTINGS)
                await interaction.followup.send(
                    f"❌ Unknown setting. Valid: {valid}", ephemeral=True)
                return
            desc, typ, default = SETTINGS[setting]
            if typ == "int":
                try:
                    int(value)
                except ValueError:
                    await interaction.followup.send(
                        f"❌ `{setting}` needs a number.", ephemeral=True)
                    return
            await self.bot.economy.db.execute(
                "INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)",
                (guild_id, setting, value))
            await self.bot.economy.db.commit()
            await interaction.followup.send(
                f"✅ `{setting}` set to `{value}`.", ephemeral=True)

        elif action == "reset":
            await self.bot.economy.db.execute(
                "DELETE FROM guild_config WHERE guild_id = ?", (guild_id,))
            await self.bot.economy.db.commit()
            await interaction.followup.send(
                "✅ All settings reset to defaults.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
