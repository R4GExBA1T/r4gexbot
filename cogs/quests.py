"""Quests & Battle Pass: daily/weekly challenges that earn Scrap.

/quests — view available quests
/quest claim — claim completed quest rewards
Admins manage via /config (quest settings in future)
"""
import random
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

RUST_COLOR = 0xCE6A2C
GOLD = 0xFFD700

# Quest definitions: (quest_id, name, description, target, reward_scrap)
QUEST_POOL = {
    "daily": [
        ("spin_wheel", "🎡 Spin the daily wheel", "Use /spin once", 1, 25),
        ("gamble_3", "🎰 Place 3 bets", "Bet in any /gamble game 3 times", 3, 30),
        ("claim_quest", "📋 Check your quests", "Open /quests (free!)", 1, 10),
    ],
    "weekly": [
        ("gamble_25", "🎰 High Roller", "Place 25 bets this week", 25, 200),
        ("clan_active", "🏰 Clan Loyalist", "Be in a clan (auto)", 1, 100),
        ("rich", "💰 Scrap Hoarder", "Hold 1000+ Scrap at once", 1, 150),
    ],
}


class Quests(commands.Cog):
    """Daily/weekly quests that reward Scrap."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS quest_progress (
                   user_id INTEGER, quest_id TEXT, period TEXT,
                   progress INTEGER DEFAULT 0, claimed INTEGER DEFAULT 0,
                   PRIMARY KEY (user_id, quest_id, period))""")
        await self.bot.economy.db.commit()

    def _period(self, quest_type: str) -> str:
        """Current period string: YYYY-MM-DD for daily, YYYY-Www for weekly."""
        now = datetime.now(timezone.utc)
        if quest_type == "daily":
            return now.strftime("%Y-%m-%d")
        # Weekly: year + ISO week
        return now.strftime("%Y-W%V")

    async def _get_quests(self, user_id: int):
        """Get user's quest status for current period."""
        result = []
        for qtype in ("daily", "weekly"):
            period = self._period(qtype)
            for qid, name, desc, target, reward in QUEST_POOL[qtype]:
                cur = await self.bot.economy.db.execute(
                    "SELECT progress, claimed FROM quest_progress WHERE user_id = ? AND quest_id = ? AND period = ?",
                    (user_id, qid, period))
                row = await cur.fetchone()
                progress = row[0] if row else 0
                claimed = row[1] if row else 0
                # Auto-check some quests
                if qid == "claim_quest":
                    progress = 1  # just by viewing
                result.append({
                    "id": qid, "name": name, "desc": desc,
                    "target": target, "reward": reward,
                    "progress": min(progress, target),
                    "claimed": claimed, "type": qtype,
                    "complete": progress >= target,
                })
        return result

    async def track(self, user_id: int, quest_id: str, amount: int = 1):
        """Increment quest progress (called by other cogs)."""
        # Find quest type
        qtype = None
        for qt in ("daily", "weekly"):
            if any(q[0] == quest_id for q in QUEST_POOL[qt]):
                qtype = qt
                break
        if not qtype:
            return
        period = self._period(qtype)
        await self.bot.economy.db.execute(
            """INSERT INTO quest_progress (user_id, quest_id, period, progress)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id, quest_id, period)
               DO UPDATE SET progress = progress + ?""",
            (user_id, quest_id, period, amount, amount))
        await self.bot.economy.db.commit()

    @app_commands.command(name="quests", description="📋 View your daily & weekly quests")
    async def quests(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        quests = await self._get_quests(interaction.user.id)

        em = discord.Embed(title="📋 Your Quests", color=RUST_COLOR,
                           description="Complete quests to earn bonus Scrap!")
        for qtype, emoji in (("daily", "📅 Daily"), ("weekly", "🗓️ Weekly")):
            lines = []
            for q in quests:
                if q["type"] != qtype:
                    continue
                status = "✅" if q["claimed"] else ("🎁" if q["complete"] else "⏳")
                lines.append(f"{status} **{q['name']}** — {q['progress']}/{q['target']}\n"
                             f"└ {q['desc']} → **{q['reward']}** Scrap")
            em.add_field(name=emoji, value="\n".join(lines), inline=False)

        # Claim button for completed unclaimed
        unclaimed = [q for q in quests if q["complete"] and not q["claimed"]]
        view = None
        if unclaimed:
            view = ClaimQuestsView(self, unclaimed)
            em.set_footer(text=f"🎁 You have {len(unclaimed)} reward(s) ready to claim!")

        await interaction.followup.send(embed=em, view=view, ephemeral=True)


class ClaimQuestsView(discord.ui.View):
    def __init__(self, cog: Quests, quests: list):
        super().__init__(timeout=120)
        self.cog = cog
        self.quests = quests

    @discord.ui.button(label="🎁 Claim All Rewards", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        total = 0
        for q in self.quests:
            # Mark claimed
            period = self.cog._period(q["type"])
            await self.cog.bot.economy.db.execute(
                "UPDATE quest_progress SET claimed = 1 WHERE user_id = ? AND quest_id = ? AND period = ?",
                (interaction.user.id, q["id"], period))
            total += q["reward"]
        await self.cog.bot.economy.db.commit()
        # Award Scrap
        await self.cog.bot.economy.add_scrap(interaction.user.id, total)
        await interaction.followup.send(
            f"🎉 Claimed **{total}** Scrap from {len(self.quests)} quest(s)!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Quests(bot))
