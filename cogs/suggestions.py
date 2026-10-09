"""Suggestions: players suggest, community votes.

/suggest <idea> — submit a suggestion
/suggestions — view top suggestions
Admins can approve/deny via buttons.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

RUST_COLOR = 0xCE6A2C


class SuggestVoteView(discord.ui.View):
    def __init__(self, cog: "Suggestions", suggestion_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.suggestion_id = suggestion_id

    @discord.ui.button(label="👍 0", style=discord.ButtonStyle.success, custom_id="sug_up")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.vote(interaction, self.suggestion_id, 1, button)

    @discord.ui.button(label="👎 0", style=discord.ButtonStyle.danger, custom_id="sug_down")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.vote(interaction, self.suggestion_id, -1, button)


class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS suggestions (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   guild_id INTEGER, user_id INTEGER, user_name TEXT,
                   text TEXT, upvotes INTEGER DEFAULT 0, downvotes INTEGER DEFAULT 0,
                   status TEXT DEFAULT 'open', created_at TEXT)""")
        await self.bot.economy.db.execute(
            """CREATE TABLE IF NOT EXISTS suggestion_votes (
                   suggestion_id INTEGER, user_id INTEGER, vote INTEGER,
                   PRIMARY KEY (suggestion_id, user_id))""")
        await self.bot.economy.db.commit()

    async def vote(self, interaction: discord.Interaction, sid: int, vote: int,
                   button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        # Check if already voted
        cur = await self.bot.economy.db.execute(
            "SELECT vote FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
            (sid, interaction.user.id))
        row = await cur.fetchone()
        if row and row[0] == vote:
            await interaction.followup.send("❌ Already voted that way!", ephemeral=True)
            return
        # Update vote
        await self.bot.economy.db.execute(
            """INSERT OR REPLACE INTO suggestion_votes (suggestion_id, user_id, vote)
               VALUES (?, ?, ?)""", (sid, interaction.user.id, vote))
        # Recount
        cur = await self.bot.economy.db.execute(
            """SELECT SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END),
                      SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END)
               FROM suggestion_votes WHERE suggestion_id = ?""", (sid,))
        up, down = await cur.fetchone()
        up, down = up or 0, down or 0
        await self.bot.economy.db.execute(
            "UPDATE suggestions SET upvotes = ?, downvotes = ? WHERE id = ?",
            (up, down, sid))
        await self.bot.economy.db.commit()
        await interaction.followup.send("✅ Vote counted!", ephemeral=True)
        # Update the message buttons
        try:
            view = SuggestVoteView(self, sid)
            view.children[0].label = f"👍 {up}"
            view.children[1].label = f"👎 {down}"
            await interaction.message.edit(view=view)
        except:
            pass

    @app_commands.command(name="suggest", description="💡 Suggest an idea for the server")
    @app_commands.describe(idea="Your suggestion")
    async def suggest(self, interaction: discord.Interaction, idea: str):
        await interaction.response.defer()
        cur = await self.bot.economy.db.execute(
            """INSERT INTO suggestions (guild_id, user_id, user_name, text, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (interaction.guild_id, interaction.user.id,
             interaction.user.display_name, idea,
             datetime.now(timezone.utc).isoformat()))
        await self.bot.economy.db.commit()
        sid = cur.lastrowid
        em = discord.Embed(
            title=f"💡 Suggestion #{sid}",
            description=idea, color=RUST_COLOR)
        em.set_footer(text=f"By {interaction.user.display_name} • Vote below!")
        view = SuggestVoteView(self, sid)
        await interaction.followup.send(embed=em, view=view)

    @app_commands.command(name="suggestions", description="📋 View top suggestions")
    async def suggestions(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cur = await self.bot.economy.db.execute(
            """SELECT id, text, upvotes, downvotes, user_name, status
               FROM suggestions WHERE guild_id = ? AND status = 'open'
               ORDER BY (upvotes - downvotes) DESC LIMIT 10""",
            (interaction.guild_id,))
        rows = await cur.fetchall()
        if not rows:
            await interaction.followup.send("📋 No suggestions yet! Use `/suggest` to add one.")
            return
        em = discord.Embed(title="📋 Top Suggestions", color=RUST_COLOR)
        for sid, text, up, down, uname, status in rows:
            score = up - down
            em.add_field(
                name=f"#{sid} — {score:+d} ({up}👍 {down}👎)",
                value=f"{text[:100]}\n_by {uname}_",
                inline=False)
        await interaction.followup.send(embed=em)


async def setup(bot: commands.Bot):
    await bot.add_cog(Suggestions(bot))
