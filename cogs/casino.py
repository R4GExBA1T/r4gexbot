"""Casino commands: /slots, /blackjack, /roulette, /coinflip.

Bets are deducted up-front through the economy service layer; winnings are
paid back through it too. Game state that only lives for one round (e.g. a
blackjack hand) stays in the discord.ui.View — economy state never does.
"""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands

from services.economy import EconomyError, EconomyService

RUST_COLOR = 0xCE6A2C  # rusty orange

# -- slots ---------------------------------------------------------------

REELS = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"]
# Three-of-a-kind multipliers; anything not listed pays 10x.
TRIPLE_MULTIPLIER = {"7️⃣": 20, "💎": 15}
PAIR_MULTIPLIER = 2


def _economy(bot: commands.Bot) -> EconomyService:
    return bot.economy  # attached in bot.py setup_hook


# -- blackjack ------------------------------------------------------------

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠️", "♥️", "♦️", "♣️"]


def draw_card() -> str:
    return f"{random.choice(RANKS)}{random.choice(SUITS)}"


def hand_value(hand: list[str]) -> int:
    total, aces = 0, 0
    for card in hand:
        rank = card[:-2]  # strip the suit (suits are 2 chars: e.g. "♠️")
        if rank in ("J", "Q", "K"):
            total += 10
        elif rank == "A":
            total += 11
            aces += 1
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def fmt_hand(hand: list[str]) -> str:
    return " ".join(hand)


class BlackjackView(discord.ui.View):
    """Interactive Hit / Stand blackjack round. Bet already deducted."""

    def __init__(self, bot: commands.Bot, user_id: int, bet: int):
        super().__init__(timeout=60)
        self.bot = bot
        self.user_id = user_id
        self.bet = bet
        self.player = [draw_card(), draw_card()]
        self.dealer = [draw_card(), draw_card()]
        self.over = False
        self.message: discord.Message | None = None  # set after sending

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ This isn't your table.", ephemeral=True
            )
            return False
        return True

    def _embed(self, hide_dealer: bool = True) -> discord.Embed:
        p_val = hand_value(self.player)
        if hide_dealer and not self.over:
            dealer_txt = f"{self.dealer[0]} ❓ (`{hand_value([self.dealer[0]])}+?`)"
        else:
            dealer_txt = f"{fmt_hand(self.dealer)} (`{hand_value(self.dealer)}`)"
        embed = discord.Embed(title="🃏 Blackjack", color=RUST_COLOR)
        embed.add_field(
            name=f"Your hand (`{p_val}`)", value=fmt_hand(self.player), inline=False
        )
        embed.add_field(name="Dealer", value=dealer_txt, inline=False)
        embed.add_field(name="Bet", value=f"{self.bet} Scrap", inline=True)
        return embed

    async def _finish(self, interaction: discord.Interaction, note: str):
        """Settle a finished round and disable the buttons."""
        self.over = True
        for child in self.children:
            child.disabled = True
        embed = self._embed(hide_dealer=False)
        embed.add_field(name="Result", value=note, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _settle_stand(self, interaction: discord.Interaction):
        """Player stood: dealer plays out, then compare."""
        while hand_value(self.dealer) < 17:
            self.dealer.append(draw_card())
        p, d = hand_value(self.player), hand_value(self.dealer)
        econ = self.bot.economy
        if d > 21:
            await econ.add_scrap(self.user_id, self.bet * 2)
            note = f"💥 Dealer busts! You win **{self.bet}** Scrap."
        elif d > p:
            note = f"😞 Dealer wins with `{d}`. You lose **{self.bet}** Scrap."
        elif d < p:
            await econ.add_scrap(self.user_id, self.bet * 2)
            note = f"🎉 You win **{self.bet}** Scrap!"
        else:
            await econ.add_scrap(self.user_id, self.bet)
            note = "🤝 Push — bet returned."
        await self._finish(interaction, note)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="👊")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.append(draw_card())
        if hand_value(self.player) > 21:
            # Bust — bet is already gone.
            await self._finish(
                interaction,
                f"💥 Bust! (`{hand_value(self.player)}`) You lose **{self.bet}** Scrap.",
            )
        elif hand_value(self.player) == 21:
            await self._settle_stand(interaction)
        else:
            await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._settle_stand(interaction)

    async def on_timeout(self):
        # Abandoned table: auto-stand and settle so the round always resolves.
        if self.over:
            return
        self.over = True
        for child in self.children:
            child.disabled = True
        while hand_value(self.dealer) < 17:
            self.dealer.append(draw_card())
        p, d = hand_value(self.player), hand_value(self.dealer)
        econ = self.bot.economy
        if d > 21 or p > d:
            await econ.add_scrap(self.user_id, self.bet * 2)
            note = f"⏰ Time expired — auto-stand. You win **{self.bet}** Scrap."
        elif p == d:
            await econ.add_scrap(self.user_id, self.bet)
            note = "⏰ Time expired — auto-stand. Push, bet returned."
        else:
            note = (
                f"⏰ Time expired — auto-stand. Dealer wins, "
                f"you lose **{self.bet}** Scrap."
            )
        if self.message is not None:
            embed = self._embed(hide_dealer=False)
            embed.add_field(name="Result", value=note, inline=False)
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass


# -- roulette --------------------------------------------------------------

# European single-zero wheel reds.
REDS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_color(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in REDS else "black"


class Casino(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _take_bet(self, interaction: discord.Interaction, bet: int) -> bool:
        """Validate + deduct a bet. Returns False (and replies) if invalid."""
        if not isinstance(bet, int) or bet <= 0:
            await interaction.followup.send(
                "❌ Bet must be a positive whole number of Scrap.", ephemeral=True
            )
            return False
        try:
            await _economy(self.bot).deduct_scrap(interaction.user.id, bet)
        except EconomyError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return False
        return True

    # -- slots ----------------------------------------------------------

    @app_commands.command(name="slots", description="Spin the 3-reel slot machine")
    @app_commands.describe(bet="How much Scrap to bet")
    async def slots(self, interaction: discord.Interaction, bet: int):
        await interaction.response.defer()
        if not await self._take_bet(interaction, bet):
            return
        spin = [random.choice(REELS) for _ in range(3)]
        line = " | ".join(spin)
        econ = _economy(self.bot)

        if spin[0] == spin[1] == spin[2]:
            mult = TRIPLE_MULTIPLIER.get(spin[0], 10)
            await econ.add_scrap(interaction.user.id, bet * mult)
            msg = (
                f"🎰 `{line}`\n**JACKPOT!** Three {spin[0]} — "
                f"**{mult}x**! You win **{bet * (mult - 1)}** Scrap."
            )
        elif spin[0] == spin[1] or spin[1] == spin[2] or spin[0] == spin[2]:
            await econ.add_scrap(interaction.user.id, bet * PAIR_MULTIPLIER)
            msg = (
                f"🎰 `{line}`\nPair! **{PAIR_MULTIPLIER}x** — "
                f"you win **{bet * (PAIR_MULTIPLIER - 1)}** Scrap."
            )
        else:
            msg = f"🎰 `{line}`\nNo luck — you lose **{bet}** Scrap."
        await interaction.followup.send(msg)

    # -- blackjack ------------------------------------------------------

    @app_commands.command(name="blackjack", description="Play blackjack vs the dealer (pays 3:2)")
    @app_commands.describe(bet="How much Scrap to bet")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        await interaction.response.defer()
        if not await self._take_bet(interaction, bet):
            return
        econ = _economy(self.bot)
        view = BlackjackView(self.bot, interaction.user.id, bet)

        # Natural blackjacks resolve immediately.
        p_val, d_val = hand_value(view.player), hand_value(view.dealer)
        if p_val == 21 or d_val == 21:
            view.over = True
            for child in view.children:
                child.disabled = True
            embed = view._embed(hide_dealer=False)
            if p_val == 21 and d_val == 21:
                await econ.add_scrap(interaction.user.id, bet)
                note = "🤝 Both blackjack — push, bet returned."
            elif p_val == 21:
                profit = (bet * 3) // 2
                await econ.add_scrap(interaction.user.id, bet + profit)
                note = f"🃏 **BLACKJACK!** Pays 3:2 — you win **{profit}** Scrap."
            else:
                note = f"😞 Dealer blackjack. You lose **{bet}** Scrap."
            embed.add_field(name="Result", value=note, inline=False)
            await interaction.followup.send(embed=embed, view=view)
            return

        await interaction.followup.send(embed=view._embed(), view=view)
        view.message = await interaction.original_response()

    # -- roulette ---------------------------------------------------------

    @app_commands.command(name="roulette", description="European roulette: bet red/black or a number 0-36")
    @app_commands.describe(bet="How much Scrap to bet", choice='"red", "black", or a number 0-36')
    async def roulette(self, interaction: discord.Interaction, bet: int, choice: str):
        await interaction.response.defer()
        choice = choice.strip().lower()
        number_choice: int | None = None
        if choice in ("red", "black"):
            pass
        elif choice.isdigit() and 0 <= int(choice) <= 36:
            number_choice = int(choice)
        else:
            await interaction.followup.send(
                '❌ Choice must be `"red"`, `"black"`, or a number 0–36.',
                ephemeral=True,
            )
            return

        if not await self._take_bet(interaction, bet):
            return
        econ = _economy(self.bot)

        spin = random.randint(0, 36)
        color = roulette_color(spin)
        color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]

        if number_choice is not None:
            if spin == number_choice:
                await econ.add_scrap(interaction.user.id, bet * 36)
                msg = (
                    f"🎡 The ball lands on {color_emoji} **{spin}**!\n"
                    f"**Straight up!** 36x — you win **{bet * 35}** Scrap."
                )
            else:
                msg = (
                    f"🎡 The ball lands on {color_emoji} **{spin}**.\n"
                    f"Not {number_choice} — you lose **{bet}** Scrap."
                )
        else:
            if color == choice:
                await econ.add_scrap(interaction.user.id, bet * 2)
                msg = (
                    f"🎡 The ball lands on {color_emoji} **{spin}** ({color})!\n"
                    f"You win **{bet}** Scrap."
                )
            else:
                msg = (
                    f"🎡 The ball lands on {color_emoji} **{spin}** ({color}).\n"
                    f"You lose **{bet}** Scrap."
                )
        await interaction.followup.send(msg)

    # -- coinflip ---------------------------------------------------------

    @app_commands.command(name="coinflip", description="Flip a coin, double or nothing")
    @app_commands.describe(bet="How much Scrap to bet")
    @app_commands.choices(
        side=[
            app_commands.Choice(name="Heads", value="heads"),
            app_commands.Choice(name="Tails", value="tails"),
        ]
    )
    async def coinflip(self, interaction: discord.Interaction, bet: int, side: str):
        await interaction.response.defer()
        if not await self._take_bet(interaction, bet):
            return
        econ = _economy(self.bot)
        result = random.choice(["heads", "tails"])
        emoji = "🪙"
        if result == side:
            await econ.add_scrap(interaction.user.id, bet * 2)
            msg = f"{emoji} It's **{result}**! You win **{bet}** Scrap."
        else:
            msg = f"{emoji} It's **{result}**. You lose **{bet}** Scrap."
        await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(Casino(bot))
