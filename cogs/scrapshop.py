"""Scrap Shop: spend Scrap on in-game items, delivered via RCON.

Tabs: Resources, Cards, Meds, Weapons, Ammo.
Players choose quantity. Admins manage via /shopadmin.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging

log = logging.getLogger("scrapshop")

# Shop tabs
TABS = ["Resources", "Cards", "Meds", "Weapons", "Ammo"]

# Default shop inventory: (tab, name, item_shortname, qty_per_unit, price)
# Prices set by Tyson 2026-10-12
DEFAULT_ITEMS = [
    # Resources
    ("Resources", "Wood x1000", "wood", 1000, 50),
    ("Resources", "Stone x1000", "stones", 1000, 50),
    ("Resources", "Metal Frags x1000", "metal.fragments", 1000, 100),
    ("Resources", "Cloth x100", "cloth", 100, 50),
    ("Resources", "Low Grade Fuel x50", "lowgradefuel", 50, 40),
    # Cards
    ("Cards", "Green Keycard", "keycard_green", 1, 75),
    ("Cards", "Blue Keycard", "keycard_blue", 1, 150),
    ("Cards", "Red Keycard", "keycard_red", 1, 300),
    ("Cards", "Fuse", "fuse", 1, 50),
    # Meds
    ("Meds", "Bandage x5", "bandage", 5, 15),
    ("Meds", "Syringe x3", "syringe.medical", 3, 50),
    # Weapons
    ("Weapons", "Crossbow", "crossbow", 1, 75),
    ("Weapons", "Salvaged Sword", "salvaged.sword", 1, 40),
    ("Weapons", "Revolver", "pistol.revolver", 1, 150),
    ("Weapons", "Waterpipe Shotgun", "shotgun.waterpipe", 1, 75),
    ("Weapons", "Double Barrel Shotgun", "shotgun.double", 1, 150),
    # Ammo
    ("Ammo", "Pistol Bullets x64", "ammo.pistol", 64, 60),
    ("Ammo", "Handmade Shells x16", "ammo.handmade.shell", 16, 30),
    ("Ammo", "Shotgun Shells x16", "ammo.shotgun", 16, 50),
    ("Ammo", "Shotgun Slugs x16", "ammo.shotgun.slug", 16, 60),
    ("Ammo", "Rifle Ammo x64", "ammo.rifle", 64, 150),
]


class TabSelect(discord.ui.Select):
    """Dropdown to choose a shop tab."""

    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(label=tab, description=f"Browse {tab}")
            for tab in TABS
        ]
        super().__init__(
            placeholder="Choose a category...",
            options=options,
            custom_id="shop_tab_select",
        )

    async def callback(self, interaction: discord.Interaction):
        tab = self.values[0]
        view = ShopView(self.cog, tab, interaction.user.id)
        await view.refresh_items()
        embed = await self.cog.build_tab_embed(tab, interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=view)


class ItemSelect(discord.ui.Select):
    """Dropdown to choose an item from the current tab."""

    def __init__(self, cog, tab: str, user_id: int, items: list):
        self.cog = cog
        self.tab = tab
        self.user_id = user_id
        self.items = items  # list of (id, name, shortname, qty, price)
        options = [
            discord.SelectOption(
                label=name[:100],
                description=f"{price} Scrap",
                value=str(item_id),
            )
            for item_id, name, _, _, price in items
        ]
        super().__init__(
            placeholder=f"Choose from {tab}...",
            options=options[:25],  # Discord limit
            custom_id="shop_item_select",
        )

    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])
        item = next((i for i in self.items if i[0] == item_id), None)
        if not item:
            await interaction.response.send_message(
                "❌ Item not found.", ephemeral=True)
            return
        _, name, shortname, qty, price = item
        view = QuantityView(self.cog, item, self.user_id)
        embed = discord.Embed(
            title=f"🛒 {name}",
            description=f"**{price}** Scrap each\n"
                        f"Delivered: {qty}x {shortname}\n\n"
                        f"Choose quantity:",
            color=0x9b59b6,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class QuantitySelect(discord.ui.Select):
    """Dropdown to choose quantity."""

    def __init__(self, cog, item: tuple, user_id: int):
        self.cog = cog
        self.item = item  # (id, name, shortname, qty, price)
        self.user_id = user_id
        _, name, _, qty, price = item
        options = []
        for mult in [1, 2, 3, 5, 10]:
            total_price = price * mult
            total_qty = qty * mult
            options.append(discord.SelectOption(
                label=f"x{mult} — {total_price} Scrap",
                description=f"Get {total_qty}x ({name})",
                value=str(mult),
            ))
        super().__init__(
            placeholder="Choose quantity...",
            options=options,
            custom_id="shop_qty_select",
        )

    async def callback(self, interaction: discord.Interaction):
        mult = int(self.values[0])
        item_id, name, shortname, qty, price = self.item
        total_price = price * mult
        total_qty = qty * mult

        # Check balance
        econ = self.cog.bot.economy
        balance = await econ.get_balance(self.user_id)
        if balance < total_price:
            await interaction.response.send_message(
                f"❌ Not enough Scrap. You have **{balance}**, need **{total_price}**.",
                ephemeral=True)
            return

        # Check linked gamertag
        cur = await econ.db.execute(
            "SELECT gamertag FROM links WHERE user_id = ?",
            (self.user_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(
                "❌ Link your gamertag first with `/linkrust`.",
                ephemeral=True)
            return
        gamertag = row[0]

        # Confirm purchase
        view = ConfirmView(self.cog, self.item, mult, self.user_id, gamertag)
        embed = discord.Embed(
            title="🛒 Confirm Purchase",
            description=f"**{name}** x{mult}\n"
                        f"Total: **{total_price}** Scrap\n"
                        f"Delivered to: **{gamertag}**\n"
                        f"Your balance: **{balance}** → **{balance - total_price}**",
            color=0xf39c12,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class ConfirmView(discord.ui.View):
    """Confirm/cancel purchase."""

    def __init__(self, cog, item: tuple, mult: int, user_id: int, gamertag: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.item = item
        self.mult = mult
        self.user_id = user_id
        self.gamertag = gamertag

    @discord.ui.button(label="✅ Buy", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction,
                  button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ This isn't your shop.", ephemeral=True)
            return
        await self.cog.process_purchase(
            interaction, self.item, self.mult, self.user_id, self.gamertag)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction,
                     button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Purchase cancelled.", embed=None, view=None)


class ShopView(discord.ui.View):
    """Main shop view with tab + item selects."""

    def __init__(self, cog, tab: str, user_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.tab = tab
        self.user_id = user_id
        self.add_item(TabSelect(cog))

    async def refresh_items(self):
        items = await self.cog.get_tab_items(self.tab)
        if items:
            self.add_item(ItemSelect(self.cog, self.tab, self.user_id, items))


class QuantityView(discord.ui.View):
    """Quantity selection view."""

    def __init__(self, cog, item: tuple, user_id: int):
        super().__init__(timeout=120)
        self.add_item(QuantitySelect(cog, item, user_id))


class ScrapShop(commands.Cog):
    """Scrap Shop — spend Scrap on in-game items."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tab TEXT NOT NULL,
                name TEXT NOT NULL,
                shortname TEXT NOT NULL,
                qty INTEGER NOT NULL DEFAULT 1,
                price INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)
        await self.bot.economy.db.commit()
        # Seed defaults if empty
        cur = await self.bot.economy.db.execute(
            "SELECT COUNT(*) FROM shop_items")
        count = (await cur.fetchone())[0]
        if count == 0:
            for tab, name, shortname, qty, price in DEFAULT_ITEMS:
                await self.bot.economy.db.execute(
                    "INSERT INTO shop_items (tab, name, shortname, qty, price)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (tab, name, shortname, qty, price))
            await self.bot.economy.db.commit()
            log.info(f"ScrapShop: seeded {len(DEFAULT_ITEMS)} items")

    async def get_tab_items(self, tab: str) -> list:
        cur = await self.bot.economy.db.execute(
            "SELECT id, name, shortname, qty, price FROM shop_items"
            " WHERE tab = ? AND enabled = 1 ORDER BY price",
            (tab,))
        return await cur.fetchall()

    async def build_tab_embed(self, tab: str, user_id: int) -> discord.Embed:
        items = await self.get_tab_items(tab)
        balance = await self.bot.economy.get_balance(user_id)
        embed = discord.Embed(
            title=f"🛒 Scrap Shop — {tab}",
            description=f"Your balance: **{balance}** Scrap\n\n"
                        f"Select an item below:",
            color=0x9b59b6,
        )
        for _, name, _, qty, price in items[:10]:
            embed.add_field(
                name=name,
                value=f"{price} Scrap",
                inline=True,
            )
        return embed

    async def process_purchase(self, interaction: discord.Interaction,
                               item: tuple, mult: int,
                               user_id: int, gamertag: str):
        item_id, name, shortname, qty, price = item
        total_price = price * mult
        total_qty = qty * mult

        await interaction.response.defer(ephemeral=True)

        # Deduct Scrap
        econ = self.bot.economy
        try:
            await econ.deduct_scrap(user_id, total_price)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Purchase failed: {e}", ephemeral=True)
            return

        # Deliver via RCON
        from services import rcon as rcon_svc
        try:
            # Split into stacks if needed (max 1000 per command for safety)
            remaining = total_qty
            while remaining > 0:
                chunk = min(remaining, 1000)
                resp = await rcon_svc.send_command(
                    f'inventory.giveto "{gamertag}" "{shortname}" "{chunk}"',
                    timeout=15.0)
                remaining -= chunk
            log.info(f"ScrapShop: {gamertag} bought {name} x{mult} "
                     f"({total_qty}x) for {total_price} Scrap")
            new_bal = await econ.get_balance(user_id)
            await interaction.followup.send(
                f"✅ Purchased **{name}** x{mult} for **{total_price}** Scrap!\n"
                f"Delivered to **{gamertag}** in-game.\n"
                f"New balance: **{new_bal}** Scrap.",
                ephemeral=True)
        except Exception as e:
            # Refund on delivery failure
            log.warning(f"ScrapShop: delivery failed for {gamertag}: {e}")
            await econ.add_scrap(user_id, total_price)
            await interaction.followup.send(
                f"❌ Delivery failed, refunded **{total_price}** Scrap. "
                f"Try again or contact staff.",
                ephemeral=True)

    @app_commands.command(name="scrapshop",
                          description="🛒 Spend Scrap on in-game items")
    async def scrapshop(self, interaction: discord.Interaction):
        """Open the Scrap Shop."""
        await interaction.response.defer(ephemeral=True)
        # Check linked
        cur = await self.bot.economy.db.execute(
            "SELECT gamertag FROM links WHERE user_id = ?",
            (interaction.user.id,))
        if not await cur.fetchone():
            await interaction.followup.send(
                "❌ Link your gamertag first with `/linkrust` to use the shop.",
                ephemeral=True)
            return
        view = ShopView(self, "Resources", interaction.user.id)
        await view.refresh_items()
        embed = await self.build_tab_embed("Resources", interaction.user.id)
        await interaction.followup.send(embed=embed, view=view,
                                        ephemeral=True)

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return (interaction.user.guild_permissions.administrator or
                interaction.guild.owner_id == interaction.user.id)

    shopadmin = app_commands.Group(
        name="shopadmin", description="🔧 Manage the Scrap Shop (admin)")

    @shopadmin.command(name="list", description="List all shop items")
    async def shopadmin_list(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "❌ Admin only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        cur = await self.bot.economy.db.execute(
            "SELECT id, tab, name, shortname, qty, price, enabled"
            " FROM shop_items ORDER BY tab, price")
        rows = await cur.fetchall()
        lines = []
        for rid, tab, name, short, qty, price, enabled in rows:
            status = "✅" if enabled else "❌"
            lines.append(f"{status} `#{rid}` [{tab}] {name} — {price} Scrap")
        # Chunk into messages (Discord 2000 char limit)
        text = "\n".join(lines) if lines else "Shop is empty."
        for i in range(0, len(text), 1900):
            await interaction.followup.send(
                text[i:i+1900] or "…", ephemeral=True)

    @shopadmin.command(name="add", description="Add a shop item")
    @app_commands.describe(
        tab="Category tab",
        name="Display name (e.g. 'Wood x1000')",
        shortname="RCON item shortname (e.g. 'wood')",
        qty="Quantity per purchase unit",
        price="Scrap price")
    @app_commands.choices(tab=[
        app_commands.Choice(name=t, value=t) for t in TABS
    ])
    async def shopadmin_add(self, interaction: discord.Interaction,
                            tab: str, name: str, shortname: str,
                            qty: int, price: int):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "❌ Admin only.", ephemeral=True)
            return
        await self.bot.economy.db.execute(
            "INSERT INTO shop_items (tab, name, shortname, qty, price)"
            " VALUES (?, ?, ?, ?, ?)",
            (tab, name, shortname, qty, price))
        await self.bot.economy.db.commit()
        await interaction.response.send_message(
            f"✅ Added **{name}** to {tab} for {price} Scrap.",
            ephemeral=True)

    @shopadmin.command(name="setprice", description="Change an item's price")
    async def shopadmin_setprice(self, interaction: discord.Interaction,
                                 item_id: int, price: int):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "❌ Admin only.", ephemeral=True)
            return
        cur = await self.bot.economy.db.execute(
            "UPDATE shop_items SET price = ? WHERE id = ?",
            (price, item_id))
        await self.bot.economy.db.commit()
        if cur.rowcount:
            await interaction.response.send_message(
                f"✅ Item #{item_id} price set to {price} Scrap.",
                ephemeral=True)
        else:
            await interaction.response.send_message(
                f"❌ Item #{item_id} not found.", ephemeral=True)

    @shopadmin.command(name="toggle", description="Enable/disable an item")
    async def shopadmin_toggle(self, interaction: discord.Interaction,
                               item_id: int):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "❌ Admin only.", ephemeral=True)
            return
        cur = await self.bot.economy.db.execute(
            "SELECT enabled, name FROM shop_items WHERE id = ?",
            (item_id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(
                f"❌ Item #{item_id} not found.", ephemeral=True)
            return
        new_state = 0 if row[0] else 1
        await self.bot.economy.db.execute(
            "UPDATE shop_items SET enabled = ? WHERE id = ?",
            (new_state, item_id))
        await self.bot.economy.db.commit()
        state = "enabled" if new_state else "disabled"
        await interaction.response.send_message(
            f"✅ **{row[1]}** {state}.", ephemeral=True)

    @shopadmin.command(name="remove", description="Delete an item")
    async def shopadmin_remove(self, interaction: discord.Interaction,
                               item_id: int):
        if not self._is_admin(interaction):
            await interaction.response.send_message(
                "❌ Admin only.", ephemeral=True)
            return
        cur = await self.bot.economy.db.execute(
            "DELETE FROM shop_items WHERE id = ?", (item_id,))
        await self.bot.economy.db.commit()
        if cur.rowcount:
            await interaction.response.send_message(
                f"✅ Item #{item_id} deleted.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"❌ Item #{item_id} not found.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ScrapShop(bot))
