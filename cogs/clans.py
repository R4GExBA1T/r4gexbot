"""Clan system: create, join, invite, roles, leaderboards."""
from __future__ import annotations

import time

CREATE_COST = 500
MAX_NAME_LEN = 32


class ClanError(Exception):
    pass


class AlreadyInClanError(ClanError):
    pass


class NotInClanError(ClanError):
    pass


class NotLeaderError(ClanError):
    pass


class NotOfficerError(ClanError):
    pass


class ClanService:
    """Clan persistence on the shared economy SQLite DB."""

    def __init__(self, db):
        self.db = db

    async def init(self) -> None:
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                leader_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS clan_members (
                clan_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at INTEGER NOT NULL,
                PRIMARY KEY (clan_id, user_id)
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS clan_invites (
                clan_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                invited_by INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (clan_id, user_id)
            )
        """)
        await self.db.commit()

    async def get_user_clan(self, user_id: int) -> dict | None:
        async with self.db.execute(
            "SELECT c.id, c.name, c.leader_id, c.created_at, m.role "
            "FROM clans c JOIN clan_members m ON m.clan_id = c.id "
            "WHERE m.user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "leader_id": row[2],
            "created_at": row[3], "role": row[4],
        }

    async def get_clan(self, clan_id: int) -> dict | None:
        async with self.db.execute(
            "SELECT id, name, leader_id, created_at FROM clans WHERE id = ?",
            (clan_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "leader_id": row[2],
                "created_at": row[3]}

    async def get_members(self, clan_id: int) -> list[dict]:
        async with self.db.execute(
            "SELECT user_id, role, joined_at FROM clan_members "
            "WHERE clan_id = ? ORDER BY "
            "CASE role WHEN 'leader' THEN 0 WHEN 'officer' THEN 1 ELSE 2 END, "
            "joined_at",
            (clan_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"user_id": r[0], "role": r[1], "joined_at": r[2]}
                for r in rows]

    async def create_clan(self, user_id: int, name: str) -> dict:
        name = name.strip()
        if not name or len(name) > MAX_NAME_LEN:
            raise ClanError(
                f"❌ Clan name must be 1-{MAX_NAME_LEN} characters.")
        if await self.get_user_clan(user_id):
            raise AlreadyInClanError("❌ You're already in a clan. Leave it first.")
        # Name taken?
        async with self.db.execute(
            "SELECT id FROM clans WHERE LOWER(name) = LOWER(?)", (name,)
        ) as cur:
            if await cur.fetchone():
                raise ClanError(f"❌ A clan named **{name}** already exists.")
        now = int(time.time())
        async with self.db.execute(
            "INSERT INTO clans (name, leader_id, created_at) VALUES (?, ?, ?)",
            (name, user_id, now)
        ) as cur:
            clan_id = cur.lastrowid
        await self.db.execute(
            "INSERT INTO clan_members (clan_id, user_id, role, joined_at) "
            "VALUES (?, ?, 'leader', ?)",
            (clan_id, user_id, now)
        )
        await self.db.commit()
        return {"id": clan_id, "name": name, "leader_id": user_id}

    async def invite(self, inviter_id: int, target_id: int) -> dict:
        if inviter_id == target_id:
            raise ClanError("❌ You can't invite yourself.")
        clan = await self.get_user_clan(inviter_id)
        if not clan:
            raise NotInClanError("❌ You're not in a clan.")
        if clan["role"] not in ("leader", "officer"):
            raise NotOfficerError("❌ Only the leader and officers can invite.")
        if await self.get_user_clan(target_id):
            raise ClanError("❌ That player is already in a clan.")
        # Already invited?
        async with self.db.execute(
            "SELECT 1 FROM clan_invites WHERE clan_id = ? AND user_id = ?",
            (clan["id"], target_id)
        ) as cur:
            if await cur.fetchone():
                raise ClanError("❌ That player already has a pending invite.")
        await self.db.execute(
            "INSERT INTO clan_invites (clan_id, user_id, invited_by, created_at) "
            "VALUES (?, ?, ?, ?)",
            (clan["id"], target_id, inviter_id, int(time.time()))
        )
        await self.db.commit()
        return clan

    async def get_invites(self, user_id: int) -> list[dict]:
        async with self.db.execute(
            "SELECT i.clan_id, c.name, i.invited_by, i.created_at "
            "FROM clan_invites i JOIN clans c ON c.id = i.clan_id "
            "WHERE i.user_id = ? ORDER BY i.created_at DESC",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"clan_id": r[0], "clan_name": r[1], "invited_by": r[2],
                 "created_at": r[3]} for r in rows]

    async def accept_invite(self, user_id: int, clan_id: int | None = None) -> dict:
        invites = await self.get_invites(user_id)
        if not invites:
            raise ClanError("❌ You have no pending clan invites.")
        if clan_id is None:
            # Accept the most recent
            invite = invites[0]
        else:
            invite = next((i for i in invites if i["clan_id"] == clan_id), None)
            if not invite:
                raise ClanError("❌ No invite from that clan.")
        if await self.get_user_clan(user_id):
            raise AlreadyInClanError("❌ You're already in a clan. Leave it first.")
        now = int(time.time())
        await self.db.execute(
            "INSERT INTO clan_members (clan_id, user_id, role, joined_at) "
            "VALUES (?, ?, 'member', ?)",
            (invite["clan_id"], user_id, now)
        )
        await self.db.execute(
            "DELETE FROM clan_invites WHERE user_id = ?", (user_id,)
        )
        await self.db.commit()
        return await self.get_clan(invite["clan_id"])

    async def decline_invite(self, user_id: int, clan_id: int | None = None) -> None:
        invites = await self.get_invites(user_id)
        if not invites:
            raise ClanError("❌ You have no pending clan invites.")
        if clan_id is None:
            await self.db.execute(
                "DELETE FROM clan_invites WHERE user_id = ?", (user_id,))
        else:
            await self.db.execute(
                "DELETE FROM clan_invites WHERE user_id = ? AND clan_id = ?",
                (user_id, clan_id))
        await self.db.commit()

    async def leave(self, user_id: int) -> str:
        clan = await self.get_user_clan(user_id)
        if not clan:
            raise NotInClanError("❌ You're not in a clan.")
        members = await self.get_members(clan["id"])
        if clan["role"] == "leader":
            if len(members) > 1:
                raise ClanError(
                    "❌ You're the leader! Promote someone to leader first "
                    "or kick all members before leaving.")
            # Last member — disband the clan
            await self.db.execute(
                "DELETE FROM clan_members WHERE clan_id = ?", (clan["id"],))
            await self.db.execute(
                "DELETE FROM clan_invites WHERE clan_id = ?", (clan["id"],))
            await self.db.execute(
                "DELETE FROM clans WHERE id = ?", (clan["id"],))
            await self.db.commit()
            return f"disbanded:{clan['name']}"
        await self.db.execute(
            "DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?",
            (clan["id"], user_id))
        await self.db.commit()
        return f"left:{clan['name']}"

    async def kick(self, kicker_id: int, target_id: int) -> None:
        clan = await self.get_user_clan(kicker_id)
        if not clan:
            raise NotInClanError("❌ You're not in a clan.")
        if clan["role"] not in ("leader", "officer"):
            raise NotOfficerError("❌ Only the leader and officers can kick.")
        target = await self.get_user_clan(target_id)
        if not target or target["id"] != clan["id"]:
            raise ClanError("❌ That player isn't in your clan.")
        if target["role"] == "leader":
            raise ClanError("❌ You can't kick the leader.")
        if clan["role"] == "officer" and target["role"] == "officer":
            raise ClanError("❌ Officers can't kick other officers.")
        await self.db.execute(
            "DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?",
            (clan["id"], target_id))
        await self.db.commit()

    async def set_role(self, leader_id: int, target_id: int, role: str) -> None:
        clan = await self.get_user_clan(leader_id)
        if not clan:
            raise NotInClanError("❌ You're not in a clan.")
        if clan["role"] != "leader":
            raise NotLeaderError("❌ Only the leader can change roles.")
        if leader_id == target_id:
            raise ClanError("❌ You can't change your own role.")
        target = await self.get_user_clan(target_id)
        if not target or target["id"] != clan["id"]:
            raise ClanError("❌ That player isn't in your clan.")
        if role == "leader":
            # Transfer leadership
            await self.db.execute(
                "UPDATE clan_members SET role = 'member' "
                "WHERE clan_id = ? AND user_id = ?",
                (clan["id"], leader_id))
            await self.db.execute(
                "UPDATE clans SET leader_id = ? WHERE id = ?",
                (target_id, clan["id"]))
        await self.db.execute(
            "UPDATE clan_members SET role = ? "
            "WHERE clan_id = ? AND user_id = ?",
            (role, clan["id"], target_id))
        await self.db.commit()

    async def leaderboard(self, limit: int = 10) -> list[dict]:
        """Top clans by member count, then total member Scrap."""
        async with self.db.execute(
            "SELECT c.id, c.name, COUNT(m.user_id) AS members "
            "FROM clans c LEFT JOIN clan_members m ON m.clan_id = c.id "
            "GROUP BY c.id ORDER BY members DESC, c.created_at ASC "
            f"LIMIT {int(limit)}"
        ) as cur:
            rows = await cur.fetchall()
        return [{"id": r[0], "name": r[1], "members": r[2]} for r in rows]

    async def clan_total_scrap(self, clan_id: int, economy) -> int:
        members = await self.get_members(clan_id)
        total = 0
        for m in members:
            total += await economy.get_balance(m["user_id"])
        return total
