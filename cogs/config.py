"""Server configuration: super user-friendly admin panel.

/config — opens a guided settings experience any admin can use.
Features: category buttons, visual setting cards, setup wizard, presets.
"""
import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C
GOLD = 0xFFD700

# (friendly name, plain-english explanation, example, is_numeric)
SETTINGS = {
    "vip_role": ("👑 VIP Role",
                 "Which role gets the hourly VIP wheel spin. Type the exact role name.",
                 "VIP", False),
    "staff_role": ("🛡️ Staff Role",
                   "Which role can manage tickets and giveaways. Type the exact role name.",
                   "Staff", False),
    "thief_role": ("💰 Heist Role",
                   "Which role can use the heist command. Type the exact role name.",
                   "Thief Princess👑", False),
    "daily_min": ("🎡 Daily Spin (Min)",
                  "Smallest prize on the daily wheel. Everyone gets one spin per day.",
                  "10", True),
    "daily_max": ("🎡 Daily Spin (Max)",
                  "Biggest common prize on the daily wheel (before jackpot).",
                  "50", True),
    "daily_jackpot": ("🎡 Daily Jackpot",
                      "The rare big win on the daily wheel.",
                      "1000", True),
    "daily_cooldown_hours": ("⏰ Daily Cooldown",
                             "Hours before someone can spin the daily wheel again.",
                             "24", True),
    "vip_min": ("⭐ VIP Spin (Min)",
                "Smallest prize on the VIP hourly wheel.",
                "5", True),
    "vip_max": ("⭐ VIP Spin (Max)",
                "Biggest common prize on the VIP wheel (before jackpot).",
                "20", True),
    "vip_jackpot": ("⭐ VIP Jackpot",
                    "The rare big win on the VIP wheel.",
                    "300", True),
    "vip_cooldown_hours": ("⏰ VIP Cooldown",
                           "Hours before a VIP can spin again.",
                           "1", True),
    "starting_scrap": ("🆕 Starting Scrap",
                       "How much Scrap brand-new users start with.",
                       "100", True),
    "min_bet": ("🎰 Minimum Bet",
                "Smallest bet allowed in casino games.",
                "10", True),
    "max_bet": ("🎰 Maximum Bet",
                "Largest bet allowed (0 = no limit).",
                "0", True),
    "hilo_multiplier": ("🃏 Hi-Lo Multiplier",
                        "Multiplier per correct guess ×100. 140 means 1.4x per win.",
                        "140", True),
    "clan_cost": ("🏰 Clan Cost",
                  "How much Scrap it costs to create a clan.",
                  "50", True),
    "welcome_channel": ("👋 Welcome Channel",
                        "Channel ID for welcome messages. 0 turns it off.\nRight-click a channel → Copy Channel ID (Developer Mode on).",
                        "0", True),
    "log_channel": ("📝 Log Channel",
                    "Channel ID for moderation logs. 0 turns it off.",
                    "0", True),
}

DEFAULTS = {k: v[2] for k, v in SETTINGS.items()}

CATEGORIES = {
    "roles": ("👑 Roles", "Who gets special perks",
              ["vip_role", "staff_role", "thief_role"]),
    "economy": ("💰 Economy", "Wheel prizes, cooldowns & starting Scrap",
                ["daily_min", "daily_max", "daily_jackpot", "daily_cooldown_hours",
                 "vip_min", "vip_max", "vip_jackpot", "vip_cooldown_hours",
                 "starting_scrap"]),
    "casino": ("🎰 Casino", "Bet limits, multipliers & clan cost",
               ["min_bet", "max_bet", "hilo_multiplier", "clan_cost"]),
    "channels": ("📢 Channels", "Welcome messages & mod logs",
                 ["welcome_channel", "log_channel"]),
}

# Quick-start presets for new servers
PRESETS = {
    "chill": ("😌 Chill Community",
              "Generous rewards, relaxed limits. Great for growing a friendly server.",
              {"daily_min": "25", "daily_max": "100", "daily_jackpot": "2000",
               "vip_min": "10", "vip_max": "50", "vip_jackpot": "500",
               "starting_scrap": "200", "min_bet": "5", "max_bet": "0",
               "clan_cost": "25"}),
    "balanced": ("⚖️ Balanced",
                 "The defaults. Fair rewards, sensible limits.",
                 {}),
    "competitive": ("🔥 Competitive",
                    "Lower rewards, higher stakes. For serious grinders.",
                    {"daily_min": "5", "daily_max": "25", "daily_jackpot": "500",
                     "vip_min": "5", "vip_max": "15", "vip_jackpot": "200",
                     "starting_scrap": "50", "min_bet": "25", "max_bet": "5000",
                     "hilo_multiplier": "130", "clan_cost": "100"}),
}


class SetValueModal(discord.ui.Modal):
    def __init__(self, cog: "Config", guild_id: int, key: str, return_view=None):
        friendly, expl, example, is_num = SETTINGS[key]
        super().__init__(title=f"{friendly}")
        self.cog = cog
        self.guild_id = guild_id
        self.key = key
        self.return_view = return_view
        self.input = discord.ui.TextInput(
            label="New value",
            placeholder=f"Example: {example}",
            required=True, max_length=100)
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.input.value.strip()
        _, _, _, is_num = SETTINGS[self.key]
        if is_num:
            try:
                int(value)
            except ValueError:
                await interaction.response.send_message(
                    "❌ That needs to be a whole number. Try again.", ephemeral=True)
                return
        await self.cog.set_value(self.guild_id, self.key, value)
        friendly = SETTINGS[self.key][0]
        await interaction.response.send_message(
            f"✅ {friendly} is now `{value}`.", ephemeral=True)


class SettingButton(discord.ui.Button):
    """One button per setting showing its current value."""

    def __init__(self, cog: "Config", guild_id: int, key: str, current: str):
        friendly, _, _, _ = SETTINGS[key]
        super().__init__(
            label=f"{friendly}: {current}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"cfg_{key}")
        self.cog = cog
        self.guild_id = guild_id
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        friendly, expl, example, _ = SETTINGS[self.key]
        current = await self.cog.get(self.guild_id, self.key)
        em = discord.Embed(title=friendly, description=expl, color=RUST_COLOR)
        em.add_field(name="Current value", value=f"`{current}`", inline=True)
        em.add_field(name="Example", value=f"`{example}`", inline=True)

        class ChangeView(discord.ui.View):
            def __init__(self2):
                super().__init__(timeout=120)

            @discord.ui.button(label="✏️ Change", style=discord.ButtonStyle.primary)
            async def change(self2, i2: discord.Interaction, b: discord.ui.Button):
                await i2.response.send_modal(SetValueModal(self.cog, self.guild_id, self.key))

        await interaction.response.send_message(embed=em, view=ChangeView(), ephemeral=True)


class CategoryView(discord.ui.View):
    """Shows all settings in a category as buttons with live values."""

    def __init__(self, cog: "Config", guild_id: int, cat_key: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.cat_key = cat_key

    @classmethod
    async def create(cls, cog: "Config", guild_id: int, cat_key: str):
        view = cls(cog, guild_id, cat_key)
        _, _, keys = CATEGORIES[cat_key]
        for key in keys:
            current = await cog.get(guild_id, key)
            view.add_item(SettingButton(cog, guild_id, key, current))
        return view

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        em, view = await self.cog.main_panel(self.guild_id)
        await interaction.response.edit_message(embed=em, view=view)


class PresetView(discord.ui.View):
    def __init__(self, cog: "Config", guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="😌 Chill Community", style=discord.ButtonStyle.secondary)
    async def chill(self, i: discord.Interaction, b: discord.ui.Button):
        await self._apply(i, "chill")

    @discord.ui.button(label="⚖️ Balanced", style=discord.ButtonStyle.secondary)
    async def balanced(self, i: discord.Interaction, b: discord.ui.Button):
        await self._apply(i, "balanced")

    @discord.ui.button(label="🔥 Competitive", style=discord.ButtonStyle.secondary)
    async def competitive(self, i: discord.Interaction, b: discord.ui.Button):
        await self._apply(i, "competitive")

    async def _apply(self, interaction: discord.Interaction, preset_key: str):
        name, desc, values = PRESETS[preset_key]
        for k, v in values.items():
            await self.cog.set_value(self.guild_id, k, v)
        # Balanced = reset to defaults
        if preset_key == "balanced":
            await self.cog.reset_all(self.guild_id)
        await interaction.response.send_message(
            f"✅ Applied preset **{name}**!\n{desc}", ephemeral=True)

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        em, view = await self.cog.main_panel(self.guild_id)
        await interaction.response.edit_message(embed=em, view=view)


class MainPanelView(discord.ui.View):
    def __init__(self, cog: "Config", guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="👑 Roles", style=discord.ButtonStyle.primary, row=0)
    async def roles(self, i: discord.Interaction, b: discord.ui.Button):
        await self._open_category(i, "roles")

    @discord.ui.button(label="💰 Economy", style=discord.ButtonStyle.primary, row=0)
    async def economy(self, i: discord.Interaction, b: discord.ui.Button):
        await self._open_category(i, "economy")

    @discord.ui.button(label="🎰 Casino", style=discord.ButtonStyle.primary, row=1)
    async def casino(self, i: discord.Interaction, b: discord.ui.Button):
        await self._open_category(i, "casino")

    @discord.ui.button(label="📢 Channels", style=discord.ButtonStyle.primary, row=1)
    async def channels(self, i: discord.Interaction, b: discord.ui.Button):
        await self._open_category(i, "channels")

    @discord.ui.button(label="✨ Quick Setup", style=discord.ButtonStyle.success, row=2)
    async def quick(self, i: discord.Interaction, b: discord.ui.Button):
        em = discord.Embed(
            title="✨ Quick Setup",
            description=("Pick a preset and you're done! You can still tweak\n"
                         "anything afterwards.\n\n" +
                         "\n".join(f"**{n}**\n{PRESETS[k][1]}" for k, (n, _, _) in
                                   [(k, PRESETS[k]) for k in PRESETS])),
            color=GOLD)
        await i.response.edit_message(embed=em, view=PresetView(self.cog, self.guild_id))

    @discord.ui.button(label="🔄 Reset Everything", style=discord.ButtonStyle.danger, row=2)
    async def reset(self, i: discord.Interaction, b: discord.ui.Button):
        await self.cog.reset_all(self.guild_id)
        await i.response.send_message("✅ Everything reset to defaults.", ephemeral=True)

    async def _open_category(self, interaction: discord.Interaction, cat_key: str):
        name, desc, _ = CATEGORIES[cat_key]
        em = discord.Embed(
            title=name, description=f"{desc}\n\nTap any setting to see what it does and change it.",
            color=RUST_COLOR)
        view = await CategoryView.create(self.cog, self.guild_id, cat_key)
        await interaction.response.edit_message(embed=em, view=view)


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

    async def main_panel(self, guild_id: int):
        em = discord.Embed(
            title="⚙️ Bot Settings",
            description=("Welcome! Tap a category below to customize the bot.\n"
                         "Every setting explains itself — no guessing.\n\n"
                         "🆕 **New here?** Hit **✨ Quick Setup** and pick a preset!"),
            color=RUST_COLOR)
        return em, MainPanelView(self, guild_id)

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    @app_commands.command(name="config", description="⚙️ Open the bot settings panel (admin)")
    async def config(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("❌ Admin only.", ephemeral=True)
            return
        em, view = await self.main_panel(interaction.guild_id)
        await interaction.response.send_message(embed=em, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
