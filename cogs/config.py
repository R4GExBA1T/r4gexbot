"""Server configuration: admins customize the bot through an interactive menu.

/config — opens the admin settings panel (no typing needed)
"""
import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C

# Setting definitions: key -> (friendly name, description, input hint)
SETTINGS = {
    # Roles
    "vip_role": ("VIP Role", "Role name that unlocks /vipspin", "e.g. VIP"),
    "staff_role": ("Staff Role", "Role name for tickets & giveaways", "e.g. Staff"),
    "thief_role": ("Heist Role", "Role name for the heist command", "e.g. Thief Princess👑"),
    # Economy
    "daily_min": ("Daily Min Prize", "Daily wheel minimum prize", "number, e.g. 10"),
    "daily_max": ("Daily Max Prize", "Daily wheel max common prize", "number, e.g. 50"),
    "daily_jackpot": ("Daily Jackpot", "Daily wheel jackpot prize", "number, e.g. 1000"),
    "daily_cooldown_hours": ("Daily Cooldown", "Hours between daily spins", "number, e.g. 24"),
    "vip_min": ("VIP Min Prize", "VIP wheel minimum prize", "number, e.g. 5"),
    "vip_max": ("VIP Max Prize", "VIP wheel max common prize", "number, e.g. 20"),
    "vip_jackpot": ("VIP Jackpot", "VIP wheel jackpot prize", "number, e.g. 300"),
    "vip_cooldown_hours": ("VIP Cooldown", "Hours between VIP spins", "number, e.g. 1"),
    "starting_scrap": ("Starting Scrap", "Scrap new users start with", "number, e.g. 100"),
    # Casino
    "min_bet": ("Min Bet", "Minimum casino bet", "number, e.g. 10"),
    "max_bet": ("Max Bet", "Maximum casino bet (0 = no limit)", "number, e.g. 0"),
    "hilo_multiplier": ("Hi-Lo Multiplier", "Per correct guess ×100 (140 = 1.4x)", "number, e.g. 140"),
    "clan_cost": ("Clan Cost", "Scrap to create a clan", "number, e.g. 50"),
    # Channels
    "welcome_channel": ("Welcome Channel", "Channel ID for welcomes (0 = off)", "channel ID or 0"),
    "log_channel": ("Log Channel", "Channel ID for mod logs (0 = off)", "channel ID or 0"),
}

# Defaults
DEFAULTS = {
    "vip_role": "VIP", "staff_role": "Staff", "thief_role": "Thief Princess👑",
    "daily_min": "10", "daily_max": "50", "daily_jackpot": "1000",
    "daily_cooldown_hours": "24", "vip_min": "5", "vip_max": "20",
    "vip_jackpot": "300", "vip_cooldown_hours": "1", "starting_scrap": "100",
    "min_bet": "10", "max_bet": "0", "hilo_multiplier": "140", "clan_cost": "50",
    "welcome_channel": "0", "log_channel": "0",
}

# Groupings for the dropdown
GROUPS = {
    "👑 Roles": ["vip_role", "staff_role", "thief_role"],
    "💰 Economy": ["daily_min", "daily_max", "daily_jackpot", "daily_cooldown_hours",
                   "vip_min", "vip_max", "vip_jackpot", "vip_cooldown_hours",
                   "starting_scrap"],
    "🎰 Casino": ["min_bet", "max_bet", "hilo_multiplier", "clan_cost"],
    "📢 Channels": ["welcome_channel", "log_channel"],
}


class SetValueModal(discord.ui.Modal):
    """Modal to enter a new value for a setting."""

    def __init__(self, cog: "Config", guild_id: int, key: str):
        super().__init__(title=f"Set {SETTINGS[key][0]}")
        self.cog = cog
        self.guild_id = guild_id
        self.key = key
        friendly, desc, hint = SETTINGS[key]
        self.value_input = discord.ui.TextInput(
            label=f"New value ({hint})",
            placeholder=f"Current: {desc}",
            required=True, max_length=100)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.value_input.value.strip()
        # Validate numbers for numeric settings
        if self.key not in ("vip_role", "staff_role", "thief_role"):
            try:
                int(value)
            except ValueError:
                await interaction.response.send_message(
                    f"❌ `{SETTINGS[self.key][0]}` needs a number.", ephemeral=True)
                return
        await self.cog.set_value(self.guild_id, self.key, value)
        friendly = SETTINGS[self.key][0]
        await interaction.response.send_message(
            f"✅ **{friendly}** set to `{value}`.", ephemeral=True)


class SettingSelect(discord.ui.Select):
    """Dropdown to pick which setting to change."""

    def __init__(self, cog: "Config", guild_id: int):
        self.cog = cog
        self.guild_id = guild_id
        options = []
        for group_name, keys in GROUPS.items():
            for key in keys:
                friendly, desc, _ = SETTINGS[key]
                options.append(discord.ui.SelectOption(
                    label=friendly, value=key,
                    description=desc[:100], emoji=group_name.split()[0]))
        super().__init__(placeholder="Choose a setting to change...",
                         options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        modal = SetValueModal(self.cog, self.guild_id, key)
        await interaction.response.send_modal(modal)


class ConfigPanelView(discord.ui.View):
    """Main config panel with buttons."""

    def __init__(self, cog: "Config", guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.add_item(SettingSelect(cog, guild_id))

    @discord.ui.button(label="👁️ View Settings", style=discord.ButtonStyle.secondary)
    async def view_btn(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        em = await self.cog.build_view_embed(self.guild_id)
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="🔄 Reset All", style=discord.ButtonStyle.danger)
    async def reset_btn(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        await self.cog.reset_all(self.guild_id)
        await interaction.response.send_message(
            "✅ All settings reset to defaults.", ephemeral=True)


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
        cur = await self.bot.economy.db.execute(
            "SELECT value FROM guild_config WHERE guild_id = ? AND key = ?",
            (guild_id, key))
        row = await cur.fetchone()
        return row[0] if row else DEFAULTS[key]

    async def get_int(self, guild_id: int, key: str) -> int:
        return int(await self.get(guild_id, key))

    async def set_value(self, guild_id: int, key: str, value: str):
        await self.bot.economy.db.execute(
            "INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)",
            (guild_id, key, value))
        await self.bot.economy.db.commit()

    async def reset_all(self, guild_id: int):
        await self.bot.economy.db.execute(
            "DELETE FROM guild_config WHERE guild_id = ?", (guild_id,))
        await self.bot.economy.db.commit()

    async def build_view_embed(self, guild_id: int) -> discord.Embed:
        em = discord.Embed(title="⚙️ Current Settings", color=RUST_COLOR)
        for group_name, keys in GROUPS.items():
            lines = []
            for key in keys:
                friendly = SETTINGS[key][0]
                val = await self.get(guild_id, key)
                lines.append(f"**{friendly}**: `{val}`")
            em.add_field(name=group_name, value="\n".join(lines), inline=False)
        return em

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="config", description="⚙️ Open the admin settings panel")
    async def config(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "❌ Admin only.", ephemeral=True)
            return
        em = discord.Embed(
            title="⚙️ Bot Settings",
            description=("Pick a setting from the dropdown below to change it,\n"
                         "or use the buttons to view all or reset."),
            color=RUST_COLOR)
        view = ConfigPanelView(self, interaction.guild_id)
        await interaction.response.send_message(embed=em, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
