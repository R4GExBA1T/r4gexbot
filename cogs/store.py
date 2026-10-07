"""Store commands: /store, /orders, /claim — real-money store integration."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.store import (
    StoreError,
    StoreService,
    ORDER_PAID,
    DELIVERY_DELIVERED,
    DELIVERY_PENDING,
)

# Set this to your store URL after deployment
STORE_URL = "https://muse.ai/s/r4ge-3x-public-store-xzxs6xxxtmqxvxgxxd"


def _store(bot: commands.Bot) -> StoreService:
    return bot.store


class Store(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="store", description="Open the R4GE 3X store")
    async def store_link(self, interaction: discord.Interaction):
        """Link to the web store."""
        embed = discord.Embed(
            title="🛒 R4GE 3X Store",
            description=(
                "Buy VIP, kits, queue skips, and more with real money.\n\n"
                f"**[Open the Store]({STORE_URL})**\n\n"
                "✅ Secure payment via Stripe\n"
                "✅ Discord roles delivered instantly\n"
                "✅ In-game kits delivered when the server launches"
            ),
            color=0x6A1B9A,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="orders", description="View your store purchase history")
    async def orders(self, interaction: discord.Interaction):
        """Show user's orders."""
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)
        orders = await store.get_user_orders(interaction.user.id)
        if not orders:
            await interaction.followup.send(
                "📭 You haven't made any store purchases yet.\n"
                f"Check out the [store]({STORE_URL})!",
                ephemeral=True)
            return

        status_emoji = {
            "pending": "⏳", "paid": "✅", "failed": "❌",
            "refunded": "↩️", "cancelled": "🚫",
        }
        lines = []
        for o in orders[:10]:
            emoji = status_emoji.get(o["status"], "❓")
            delivery = await store.get_delivery_for_order(o["id"])
            delivery_str = ""
            if delivery:
                if delivery["status"] == DELIVERY_DELIVERED:
                    delivery_str = " 📦 delivered"
                elif delivery["status"] == DELIVERY_PENDING:
                    delivery_str = " 📦 delivery pending"
            lines.append(
                f"{emoji} **{o['product_name']}** — {o['amount_display']} "
                f"({o['status']}){delivery_str}"
            )

        embed = discord.Embed(
            title="🧾 Your Orders",
            description="\n".join(lines),
            color=0x6A1B9A,
        )
        if len(orders) > 10:
            embed.set_footer(text=f"Showing 10 of {len(orders)} orders")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="claim", description="Claim your purchased items")
    async def claim(self, interaction: discord.Interaction):
        """Check for pending deliveries and attempt them."""
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)

        # Get user's paid orders with pending deliveries
        orders = await store.get_user_orders(interaction.user.id)
        pending = []
        for o in orders:
            if o["status"] != ORDER_PAID:
                continue
            delivery = await store.get_delivery_for_order(o["id"])
            if delivery and delivery["status"] == DELIVERY_PENDING:
                pending.append((o, delivery))

        if not pending:
            await interaction.followup.send(
                "✅ Nothing to claim! All your purchases are delivered.\n"
                f"Buy more at the [store]({STORE_URL})",
                ephemeral=True)
            return

        # Attempt Discord role deliveries
        results = []
        guild = interaction.guild
        for order, delivery in pending:
            if delivery["delivery_type"] == "discord_role":
                role_id = delivery.get("delivery_data", {}).get("role_id")
                # Also check product delivery_data
                product = await store.get_product(order["product_id"])
                role_id = role_id or (product.get("delivery_data", {}).get("role_id") if product else None)
                if role_id and guild:
                    role = guild.get_role(int(role_id))
                    if role:
                        try:
                            await interaction.user.add_roles(role, reason=f"Store purchase #{order['id']}")
                            await store.record_delivery_attempt(
                                delivery["id"], True,
                                {"method": "discord_role", "role_id": role_id})
                            results.append(f"✅ **{order['product_name']}** — {role.name} role granted!")
                        except discord.Forbidden:
                            await store.record_delivery_attempt(
                                delivery["id"], False,
                                {"error": "Missing permissions to grant role"})
                            results.append(f"❌ **{order['product_name']}** — couldn't grant role (contact staff)")
                        except Exception as e:
                            await store.record_delivery_attempt(
                                delivery["id"], False, {"error": str(e)[:200]})
                            results.append(f"❌ **{order['product_name']}** — delivery failed (contact staff)")
                    else:
                        results.append(f"⏳ **{order['product_name']}** — role not found (contact staff)")
                else:
                    results.append(f"⏳ **{order['product_name']}** — awaiting manual delivery")
            elif delivery["delivery_type"] == "rcon_kit":
                results.append(
                    f"⏳ **{order['product_name']}** — in-game kit queued for server launch. "
                    "You'll receive it automatically when the Rust server goes live.")
            else:
                results.append(f"⏳ **{order['product_name']}** — pending delivery")

        embed = discord.Embed(
            title="📦 Claim Results",
            description="\n".join(results),
            color=0x6A1B9A,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Staff: product management ─────────────────────────────

    store_admin = app_commands.Group(
        name="storeadmin",
        description="Store management (staff only)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @store_admin.command(name="products", description="List all store products")
    async def admin_products(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)
        products = await store.get_products(active_only=False)
        if not products:
            await interaction.followup.send("📭 No products yet.", ephemeral=True)
            return
        lines = []
        for p in products:
            status = "✅" if p["active"] else "🚫"
            lines.append(
                f"{status} `#{p['id']}` **{p['name']}** — {p['price_display']} "
                f"({p['delivery_type']})"
            )
        embed = discord.Embed(
            title="🛒 Store Products",
            description="\n".join(lines),
            color=0x6A1B9A,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @store_admin.command(name="addproduct", description="Add a new store product")
    @app_commands.describe(
        name="Product name",
        price="Price in USD (e.g. 9.99)",
        delivery_type="How it's delivered",
        description="What the player gets",
        role="Discord role to grant (for discord_role type)",
    )
    @app_commands.choices(delivery_type=[
        app_commands.Choice(name="Discord Role", value="discord_role"),
        app_commands.Choice(name="In-Game Kit (RCON)", value="rcon_kit"),
        app_commands.Choice(name="Subscription", value="subscription"),
    ])
    async def admin_addproduct(
        self, interaction: discord.Interaction,
        name: str, price: float, delivery_type: str,
        description: str = "", role: discord.Role | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)
        try:
            price_cents = int(round(price * 100))
            delivery_data = {}
            if delivery_type == "discord_role" and role:
                delivery_data["role_id"] = role.id
                delivery_data["role_name"] = role.name
            product = await store.create_product(
                name=name, description=description or name,
                price_cents=price_cents, delivery_type=delivery_type,
                delivery_data=delivery_data)
        except StoreError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Product **{product['name']}** added — {product['price_display']} "
            f"(`#{product['id']}`)", ephemeral=True)

    @store_admin.command(name="setprice", description="Change a product's price")
    @app_commands.describe(product_id="Product ID", price="New price in USD")
    async def admin_setprice(self, interaction: discord.Interaction,
                             product_id: int, price: float):
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)
        try:
            product = await store.update_product(
                product_id, price_cents=int(round(price * 100)))
        except StoreError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ **{product['name']}** is now {product['price_display']}",
            ephemeral=True)

    @store_admin.command(name="toggle", description="Activate/deactivate a product")
    @app_commands.describe(product_id="Product ID")
    async def admin_toggle(self, interaction: discord.Interaction, product_id: int):
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)
        product = await store.get_product(product_id)
        if not product:
            await interaction.followup.send("❌ Product not found.", ephemeral=True)
            return
        new_active = not product["active"]
        await store.update_product(product_id, active=new_active)
        status = "activated ✅" if new_active else "deactivated 🚫"
        await interaction.followup.send(
            f"**{product['name']}** {status}", ephemeral=True)

    @store_admin.command(name="pending", description="View pending deliveries")
    async def admin_pending(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        store = _store(self.bot)
        pending = await store.get_pending_deliveries(20)
        if not pending:
            await interaction.followup.send(
                "✅ No pending deliveries!", ephemeral=True)
            return
        lines = []
        for d in pending:
            lines.append(
                f"📦 Order `#{d['order_id']}` — **{d['product_name']}** "
                f"(<@{d['user_id']}>) — {d['delivery_type']} "
                f"({d['attempts']} attempts)"
            )
        embed = discord.Embed(
            title="📦 Pending Deliveries",
            description="\n".join(lines),
            color=0xFF9800,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    store = StoreService(bot.economy.db)
    await store.init()
    bot.store = store
    await bot.add_cog(Store(bot))
