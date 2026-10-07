"""Real-money store (Tip4Serv-like): products, orders, Stripe payments, delivery tracking."""
from __future__ import annotations

import json
import time


class StoreError(Exception):
    pass


class ProductNotFoundError(StoreError):
    pass


class OrderNotFoundError(StoreError):
    pass


# Product delivery types
DELIVERY_DISCORD_ROLE = "discord_role"  # Grant a Discord role
DELIVERY_RCON_KIT = "rcon_kit"          # In-game kit via RCON (when server live)
DELIVERY_SUBSCRIPTION = "subscription"  # Recurring (Stripe subscription)

# Order statuses
ORDER_PENDING = "pending"      # Created, awaiting payment
ORDER_PAID = "paid"            # Payment confirmed
ORDER_FAILED = "failed"        # Payment failed
ORDER_REFUNDED = "refunded"    # Refunded
ORDER_CANCELLED = "cancelled"  # Cancelled before payment

# Delivery statuses
DELIVERY_PENDING = "pending"
DELIVERY_DELIVERED = "delivered"
DELIVERY_FAILED = "failed"


class StoreService:
    """Real-money store persistence on the shared economy SQLite DB."""

    def __init__(self, db):
        self.db = db

    async def init(self) -> None:
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS store_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'usd',
                delivery_type TEXT NOT NULL,
                delivery_data TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS store_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                stripe_session_id TEXT UNIQUE,
                stripe_payment_intent TEXT,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'usd',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                paid_at INTEGER,
                FOREIGN KEY (product_id) REFERENCES store_products(id)
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS store_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                delivery_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at INTEGER,
                delivered_at INTEGER,
                details TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (order_id) REFERENCES store_orders(id)
            )
        """)
        # Index for fast order lookups by user
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_store_orders_user
            ON store_orders(user_id)
        """)
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_store_orders_session
            ON store_orders(stripe_session_id)
        """)
        await self.db.commit()

    # ── Products ──────────────────────────────────────────────

    async def create_product(self, name: str, description: str, price_cents: int,
                             delivery_type: str, delivery_data: dict | None = None,
                             currency: str = "usd") -> dict:
        name = name.strip()
        if not name:
            raise StoreError("❌ Product name can't be empty.")
        if price_cents < 0:
            raise StoreError("❌ Price can't be negative.")
        if delivery_type not in (DELIVERY_DISCORD_ROLE, DELIVERY_RCON_KIT,
                                 DELIVERY_SUBSCRIPTION):
            raise StoreError(f"❌ Invalid delivery type: {delivery_type}")
        now = int(time.time())
        try:
            async with self.db.execute(
                "INSERT INTO store_products (name, description, price_cents, currency, "
                "delivery_type, delivery_data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, description, price_cents, currency.lower(),
                 delivery_type, json.dumps(delivery_data or {}), now, now)
            ) as cur:
                product_id = cur.lastrowid
            await self.db.commit()
        except Exception:
            raise StoreError(f"❌ A product named **{name}** already exists.")
        return await self.get_product(product_id)

    async def get_product(self, product_id: int) -> dict | None:
        async with self.db.execute(
            "SELECT id, name, description, price_cents, currency, delivery_type, "
            "delivery_data, active, created_at, updated_at "
            "FROM store_products WHERE id = ?", (product_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_product(row)

    async def get_products(self, active_only: bool = True) -> list[dict]:
        query = ("SELECT id, name, description, price_cents, currency, delivery_type, "
                 "delivery_data, active, created_at, updated_at FROM store_products")
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY price_cents ASC"
        async with self.db.execute(query) as cur:
            rows = await cur.fetchall()
        return [self._row_to_product(r) for r in rows]

    async def update_product(self, product_id: int, **kwargs) -> dict:
        allowed = {"name", "description", "price_cents", "currency",
                   "delivery_type", "delivery_data", "active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise StoreError("❌ No valid fields to update.")
        if "delivery_data" in updates and isinstance(updates["delivery_data"], dict):
            updates["delivery_data"] = json.dumps(updates["delivery_data"])
        updates["updated_at"] = int(time.time())
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await self.db.execute(
            f"UPDATE store_products SET {set_clause} WHERE id = ?",
            (*updates.values(), product_id)
        )
        await self.db.commit()
        product = await self.get_product(product_id)
        if not product:
            raise ProductNotFoundError("❌ Product not found.")
        return product

    async def deactivate_product(self, product_id: int) -> None:
        await self.db.execute(
            "UPDATE store_products SET active = 0, updated_at = ? WHERE id = ?",
            (int(time.time()), product_id)
        )
        await self.db.commit()

    def _row_to_product(self, row) -> dict:
        return {
            "id": row[0], "name": row[1], "description": row[2],
            "price_cents": row[3], "currency": row[4],
            "delivery_type": row[5], "delivery_data": json.loads(row[6]),
            "active": bool(row[7]), "created_at": row[8], "updated_at": row[9],
            "price_display": f"${row[3] / 100:.2f}",
        }

    # ── Orders ────────────────────────────────────────────────

    async def create_order(self, user_id: int, product_id: int) -> dict:
        product = await self.get_product(product_id)
        if not product or not product["active"]:
            raise ProductNotFoundError("❌ That product isn't available.")
        now = int(time.time())
        async with self.db.execute(
            "INSERT INTO store_orders (user_id, product_id, amount_cents, currency, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, product_id, product["price_cents"], product["currency"],
             ORDER_PENDING, now)
        ) as cur:
            order_id = cur.lastrowid
        await self.db.commit()
        return await self.get_order(order_id)

    async def get_order(self, order_id: int) -> dict | None:
        async with self.db.execute(
            "SELECT o.id, o.user_id, o.product_id, o.stripe_session_id, "
            "o.stripe_payment_intent, o.amount_cents, o.currency, o.status, "
            "o.created_at, o.paid_at, p.name as product_name "
            "FROM store_orders o JOIN store_products p ON p.id = o.product_id "
            "WHERE o.id = ?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_order(row)

    async def get_order_by_session(self, stripe_session_id: str) -> dict | None:
        async with self.db.execute(
            "SELECT o.id, o.user_id, o.product_id, o.stripe_session_id, "
            "o.stripe_payment_intent, o.amount_cents, o.currency, o.status, "
            "o.created_at, o.paid_at, p.name as product_name "
            "FROM store_orders o JOIN store_products p ON p.id = o.product_id "
            "WHERE o.stripe_session_id = ?", (stripe_session_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return self._row_to_order(row)

    async def get_user_orders(self, user_id: int, limit: int = 20) -> list[dict]:
        async with self.db.execute(
            "SELECT o.id, o.user_id, o.product_id, o.stripe_session_id, "
            "o.stripe_payment_intent, o.amount_cents, o.currency, o.status, "
            "o.created_at, o.paid_at, p.name as product_name "
            "FROM store_orders o JOIN store_products p ON p.id = o.product_id "
            "WHERE o.user_id = ? ORDER BY o.created_at DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_order(r) for r in rows]

    async def set_order_session(self, order_id: int, stripe_session_id: str) -> None:
        await self.db.execute(
            "UPDATE store_orders SET stripe_session_id = ? WHERE id = ?",
            (stripe_session_id, order_id)
        )
        await self.db.commit()

    async def mark_paid(self, order_id: int, stripe_payment_intent: str | None = None) -> dict:
        now = int(time.time())
        await self.db.execute(
            "UPDATE store_orders SET status = ?, paid_at = ?, "
            "stripe_payment_intent = COALESCE(?, stripe_payment_intent) "
            "WHERE id = ?",
            (ORDER_PAID, now, stripe_payment_intent, order_id)
        )
        # Create pending delivery record
        order = await self.get_order(order_id)
        product = await self.get_product(order["product_id"])
        await self.db.execute(
            "INSERT OR IGNORE INTO store_deliveries (order_id, delivery_type, status) "
            "VALUES (?, ?, ?)",
            (order_id, product["delivery_type"], DELIVERY_PENDING)
        )
        await self.db.commit()
        return await self.get_order(order_id)

    async def mark_failed(self, order_id: int) -> None:
        await self.db.execute(
            "UPDATE store_orders SET status = ? WHERE id = ?",
            (ORDER_FAILED, order_id)
        )
        await self.db.commit()

    async def mark_refunded(self, order_id: int) -> None:
        await self.db.execute(
            "UPDATE store_orders SET status = ? WHERE id = ?",
            (ORDER_REFUNDED, order_id)
        )
        await self.db.commit()

    def _row_to_order(self, row) -> dict:
        return {
            "id": row[0], "user_id": row[1], "product_id": row[2],
            "stripe_session_id": row[3], "stripe_payment_intent": row[4],
            "amount_cents": row[5], "currency": row[6], "status": row[7],
            "created_at": row[8], "paid_at": row[9], "product_name": row[10],
            "amount_display": f"${row[5] / 100:.2f}",
        }

    # ── Deliveries ────────────────────────────────────────────

    async def get_pending_deliveries(self, limit: int = 50) -> list[dict]:
        async with self.db.execute(
            "SELECT d.id, d.order_id, d.delivery_type, d.status, d.attempts, "
            "d.last_attempt_at, d.delivered_at, d.details, "
            "o.user_id, o.product_id, p.name as product_name, "
            "p.delivery_data "
            "FROM store_deliveries d "
            "JOIN store_orders o ON o.id = d.order_id "
            "JOIN store_products p ON p.id = o.product_id "
            "WHERE d.status = ? ORDER BY d.id ASC LIMIT ?",
            (DELIVERY_PENDING, limit)
        ) as cur:
            rows = await cur.fetchall()
        return [{
            "id": r[0], "order_id": r[1], "delivery_type": r[2],
            "status": r[3], "attempts": r[4], "last_attempt_at": r[5],
            "delivered_at": r[6], "details": json.loads(r[7]),
            "user_id": r[8], "product_id": r[9], "product_name": r[10],
            "delivery_data": json.loads(r[11]),
        } for r in rows]

    async def record_delivery_attempt(self, delivery_id: int,
                                     success: bool,
                                     details: dict | None = None) -> None:
        now = int(time.time())
        if success:
            await self.db.execute(
                "UPDATE store_deliveries SET status = ?, delivered_at = ?, "
                "attempts = attempts + 1, last_attempt_at = ?, details = ? "
                "WHERE id = ?",
                (DELIVERY_DELIVERED, now, now,
                 json.dumps(details or {}), delivery_id)
            )
        else:
            await self.db.execute(
                "UPDATE store_deliveries SET attempts = attempts + 1, "
                "last_attempt_at = ?, details = ? WHERE id = ?",
                (now, json.dumps(details or {}), delivery_id)
            )
        await self.db.commit()

    async def get_delivery_for_order(self, order_id: int) -> dict | None:
        async with self.db.execute(
            "SELECT id, order_id, delivery_type, status, attempts, "
            "last_attempt_at, delivered_at, details "
            "FROM store_deliveries WHERE order_id = ?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "order_id": row[1], "delivery_type": row[2],
            "status": row[3], "attempts": row[4],
            "last_attempt_at": row[5], "delivered_at": row[6],
            "details": json.loads(row[7]),
        }
