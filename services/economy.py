"""Scrap economy service layer.

Every balance change in Ximmy MUST go through this module. Discord command
cogs call these async functions; they never touch SQL directly.

All cooldowns are computed from timestamps stored in SQLite, so nothing
breaks when the bot restarts.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import aiosqlite

STARTING_SCRAP = 100
DAY = 86_400
HOUR = 3_600
WEEK = 7 * DAY

# Weighted daily wheel: (payout, weight). Weights sum to 100.
# "common" resolves to a random 10-50 payout.
DAILY_WHEEL_PAYOUTS = [1000, 250, 100, "common"]
DAILY_WHEEL_WEIGHTS = [1, 4, 15, 80]  # jackpot ~1%, rare 4%, uncommon 15%

# VIP hourly wheel: its own spin, separate from the daily.
# "common" resolves to a random 5-20 payout.
VIP_WHEEL_PAYOUTS = [300, 100, 50, "common"]
VIP_WHEEL_WEIGHTS = [2, 8, 15, 75]  # jackpot ~2%, rare 8%, uncommon 15%

WEEKLY_BASE = 500


class EconomyError(Exception):
    """Base class for user-facing economy errors."""


class InsufficientFundsError(EconomyError):
    def __init__(self, balance: int, bet: int):
        self.balance = balance
        self.bet = bet
        super().__init__(
            f"❌ Not enough Scrap — you have **{balance}** but tried to bet **{bet}**."
        )


class InvalidAmountError(EconomyError):
    def __init__(self, message: str = "❌ Amount must be a positive whole number."):
        super().__init__(message)


class SelfTransferError(EconomyError):
    def __init__(self):
        super().__init__("❌ You can't send Scrap to yourself. Nice try though.")


class CooldownError(EconomyError):
    """Raised when a timed reward is still on cooldown."""

    def __init__(self, remaining_seconds: int, label: str = "reward"):
        self.remaining = max(0, int(remaining_seconds))
        super().__init__(
            f"⏳ That {label} is on cooldown — come back in **{format_cooldown(self.remaining)}**."
        )


def format_cooldown(seconds: int) -> str:
    """Turn seconds into a friendly 'Xh Ym' / 'Ym' string."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def streak_bonus_pct(streak: int) -> int:
    """+10% per consecutive day, capped at +70% (7+ day streak)."""
    return min(max(int(streak), 0), 7) * 10


@dataclass
class DailyResult:
    base: int
    bonus_pct: int
    total: int
    streak: int
    new_balance: int
    tier: str  # "jackpot" | "rare" | "uncommon" | "common"


@dataclass
class WeeklyResult:
    base: int
    bonus_pct: int
    total: int
    new_balance: int


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    balance     INTEGER NOT NULL DEFAULT 100,
    last_daily  INTEGER,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    last_weekly INTEGER,
    last_vip_spin INTEGER
);
CREATE TABLE IF NOT EXISTS links (
    discord_id INTEGER PRIMARY KEY,
    gamertag   TEXT NOT NULL
);
"""


class EconomyService:
    """Async service layer for the Scrap economy (SQLite via aiosqlite)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.executescript(SCHEMA)
        # Migration for DBs created before the VIP spin column existed.
        async with self._db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "last_vip_spin" not in cols:
            await self._db.execute("ALTER TABLE users ADD COLUMN last_vip_spin INTEGER")
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("EconomyService not connected — call connect() first.")
        return self._db

    # -- core balance operations -----------------------------------------

    async def ensure_user(self, user_id: int) -> None:
        """Create the user row (with starting Scrap) if it doesn't exist."""
        await self.db.execute(
            "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, ?)",
            (int(user_id), STARTING_SCRAP),
        )
        await self.db.commit()

    async def get_balance(self, user_id: int) -> int:
        await self.ensure_user(user_id)
        async with self.db.execute(
            "SELECT balance FROM users WHERE user_id = ?", (int(user_id),)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0])

    async def add_scrap(self, user_id: int, amount: int) -> int:
        """Add Scrap; returns the new balance."""
        if amount <= 0:
            raise InvalidAmountError()
        await self.ensure_user(user_id)
        await self.db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (int(amount), int(user_id)),
        )
        await self.db.commit()
        return await self.get_balance(user_id)

    async def deduct_scrap(self, user_id: int, amount: int) -> int:
        """Remove Scrap; raises InsufficientFundsError. Returns new balance."""
        if amount <= 0:
            raise InvalidAmountError()
        balance = await self.get_balance(user_id)
        if amount > balance:
            raise InsufficientFundsError(balance, amount)
        await self.db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (int(amount), int(user_id)),
        )
        await self.db.commit()
        return balance - amount

    async def transfer(self, from_id: int, to_id: int, amount: int) -> tuple[int, int]:
        """Move Scrap between users. Returns (sender_balance, receiver_balance)."""
        from_id, to_id = int(from_id), int(to_id)
        if from_id == to_id:
            raise SelfTransferError()
        if amount <= 0:
            raise InvalidAmountError()
        sender_balance = await self.get_balance(from_id)
        if amount > sender_balance:
            raise InsufficientFundsError(sender_balance, amount)
        await self.ensure_user(to_id)
        await self.db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (amount, from_id),
        )
        await self.db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, to_id),
        )
        await self.db.commit()
        return sender_balance - amount, await self.get_balance(to_id)

    # -- timed rewards ----------------------------------------------------

    async def claim_daily(self, user_id: int, now: int | None = None) -> DailyResult:
        """Spin the daily wheel. Raises CooldownError if < 24h since last spin."""
        now = int(now if now is not None else time.time())
        await self.ensure_user(user_id)
        async with self.db.execute(
            "SELECT balance, last_daily, daily_streak FROM users WHERE user_id = ?",
            (int(user_id),),
        ) as cur:
            balance, last_daily, streak = await cur.fetchone()

        if last_daily is not None and now - last_daily < DAY:
            raise CooldownError(DAY - (now - last_daily), "daily wheel spin")

        # Streak continues if the last spin was within the last 48h.
        streak = streak + 1 if (last_daily is not None and now - last_daily < 2 * DAY) else 1

        pick = random.choices(DAILY_WHEEL_PAYOUTS, weights=DAILY_WHEEL_WEIGHTS, k=1)[0]
        if pick == "common":
            base, tier = random.randint(10, 50), "common"
        elif pick == 100:
            base, tier = 100, "uncommon"
        elif pick == 250:
            base, tier = 250, "rare"
        else:
            base, tier = 1000, "jackpot"

        bonus_pct = streak_bonus_pct(streak)
        total = base + (base * bonus_pct) // 100
        new_balance = balance + total

        await self.db.execute(
            "UPDATE users SET balance = ?, last_daily = ?, daily_streak = ? WHERE user_id = ?",
            (new_balance, now, streak, int(user_id)),
        )
        await self.db.commit()
        return DailyResult(base, bonus_pct, total, streak, new_balance, tier)

    async def claim_vip_spin(self, user_id: int, now: int | None = None) -> DailyResult:
        """VIP hourly wheel spin — its own wheel, separate from the daily.
        Raises CooldownError if < 1h since last VIP spin."""
        now = int(now if now is not None else time.time())
        await self.ensure_user(user_id)
        async with self.db.execute(
            "SELECT balance, last_vip_spin FROM users WHERE user_id = ?",
            (int(user_id),),
        ) as cur:
            balance, last_vip = await cur.fetchone()

        if last_vip is not None and now - last_vip < HOUR:
            raise CooldownError(HOUR - (now - last_vip), "VIP wheel spin")

        pick = random.choices(VIP_WHEEL_PAYOUTS, weights=VIP_WHEEL_WEIGHTS, k=1)[0]
        if pick == "common":
            base, tier = random.randint(5, 20), "common"
        elif pick == 50:
            base, tier = 50, "uncommon"
        elif pick == 100:
            base, tier = 100, "rare"
        else:
            base, tier = 300, "jackpot"

        new_balance = balance + base

        await self.db.execute(
            "UPDATE users SET balance = ?, last_vip_spin = ? WHERE user_id = ?",
            (new_balance, now, int(user_id)),
        )
        await self.db.commit()
        return DailyResult(base, 0, base, 0, new_balance, tier)

    async def reset_timer(self, user_id: int, timer: str) -> None:
        """Reset a cooldown timer for a user. timer: 'daily' | 'vip' | 'weekly'."""
        column = {"daily": "last_daily", "vip": "last_vip_spin", "weekly": "last_weekly"}.get(timer)
        if column is None:
            raise ValueError(f"Unknown timer: {timer}")
        await self.ensure_user(user_id)
        await self.db.execute(
            f"UPDATE users SET {column} = NULL WHERE user_id = ?",
            (int(user_id),),
        )
        await self.db.commit()

    async def claim_weekly(self, user_id: int, now: int | None = None) -> WeeklyResult:
        """Claim the weekly reward. Raises CooldownError if < 7d since last claim."""
        now = int(now if now is not None else time.time())
        await self.ensure_user(user_id)
        async with self.db.execute(
            "SELECT balance, last_weekly, daily_streak FROM users WHERE user_id = ?",
            (int(user_id),),
        ) as cur:
            balance, last_weekly, streak = await cur.fetchone()

        if last_weekly is not None and now - last_weekly < WEEK:
            raise CooldownError(WEEK - (now - last_weekly), "weekly reward")

        bonus_pct = streak_bonus_pct(streak) if streak >= 5 else 0
        total = WEEKLY_BASE + (WEEKLY_BASE * bonus_pct) // 100
        new_balance = balance + total

        await self.db.execute(
            "UPDATE users SET balance = ?, last_weekly = ? WHERE user_id = ?",
            (new_balance, now, int(user_id)),
        )
        await self.db.commit()
        return WeeklyResult(WEEKLY_BASE, bonus_pct, total, new_balance)

    async def get_leaderboard(self, limit: int = 10) -> list[tuple[int, int]]:
        """Top users by balance: [(user_id, balance), ...]."""
        async with self.db.execute(
            "SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?",
            (int(limit),),
        ) as cur:
            rows = await cur.fetchall()
        return [(int(uid), int(bal)) for uid, bal in rows]

    # -- Rust Console gamertag linking (for future server rewards) --------

    async def link_rust(self, discord_id: int, gamertag: str) -> None:
        await self.ensure_user(discord_id)
        await self.db.execute(
            "INSERT INTO links (discord_id, gamertag) VALUES (?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET gamertag = excluded.gamertag",
            (int(discord_id), gamertag),
        )
        await self.db.commit()

    async def unlink_rust(self, discord_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM links WHERE discord_id = ?", (int(discord_id),)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def get_gamertag(self, discord_id: int) -> str | None:
        async with self.db.execute(
            "SELECT gamertag FROM links WHERE discord_id = ?", (int(discord_id),)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None
