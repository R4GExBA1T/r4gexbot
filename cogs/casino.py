"""Casino commands: /slots, /blackjack, /roulette, /coinflip.

Bets are deducted up-front through the economy service layer; winnings are
paid back through it too. Game state that only lives for one round (e.g. a
blackjack hand) stays in the discord.ui.View — economy state never does.
"""

from __future__ import annotations

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from services.coinflip import flip_coin_gif
from services.roulette import roulette_spin_gif
from services.slots import slots_spin_gif, SYMBOLS
from services.blackjack import render_blackjack_table
from services.crash import roll_crash_point, crash_animation_gif
from services.mines import render_mines_board, mines_multiplier
from services.plinko import plinko_animation_gif, MULTIPLIERS
from services.hilo import render_hilo_table, new_card, card_value
from services.economy import EconomyError, EconomyService

RUST_COLOR = 0xCE6A2C  # rusty orange

# -- slots ---------------------------------------------------------------

# Rust-themed slot symbols (keys match services/slots.py).
REELS = ["seven", "supplydrop", "ak", "facemask", "sulfur", "scrap"]
# Display names for results.
REEL_NAMES = {
    "seven": "Golden 7",
    "supplydrop": "Supply Drop",
    "ak": "AK-47",
    "facemask": "Facemask",
    "sulfur": "Sulfur",
    "scrap": "Scrap",
}
# Three-of-a-kind multipliers; anything not listed pays 10x.
TRIPLE_MULTIPLIER = {"seven": 20, "supplydrop": 15}
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
        embed.set_image(url="attachment://blackjack.png")
        embed.add_field(
            name=f"Your hand (`{p_val}`)", value=fmt_hand(self.player), inline=False
        )
        embed.add_field(name="Dealer", value=dealer_txt, inline=False)
        embed.add_field(name="Bet", value=f"{self.bet} Scrap", inline=True)
        return embed

    def _table_file(self, hide_dealer: bool = True) -> discord.File:
        """Render the current table state as a Discord file."""
        buf = render_blackjack_table(self.player, self.dealer, hide_dealer)
        return discord.File(buf, filename="blackjack.png")

    async def _finish(self, interaction: discord.Interaction, note: str):
        """Settle a finished round and disable the buttons."""
        self.over = True
        for child in self.children:
            child.disabled = True
        embed = self._embed(hide_dealer=False)
        embed.add_field(name="Result", value=note, inline=False)
        file = self._table_file(hide_dealer=False)
        await interaction.response.edit_message(embed=embed, view=self,
                                               attachments=[file])

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
            file = self._table_file()
            await interaction.response.edit_message(embed=self._embed(), view=self,
                                                   attachments=[file])

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
# NOTE: The pre-rendered wheel image (roulette_wheel_perfect.png) has
# inverted red/black pockets vs standard European roulette, so this set
# is inverted to match what players see on the wheel. Fixed 2026-10-07.
REDS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}


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
        names = [REEL_NAMES[s] for s in spin]
        line = " | ".join(names)
        econ = _economy(self.bot)

        try:
            gif = await asyncio.to_thread(slots_spin_gif, spin)
        except Exception:
            gif = None

        if spin[0] == spin[1] == spin[2]:
            mult = TRIPLE_MULTIPLIER.get(spin[0], 10)
            await econ.add_scrap(interaction.user.id, bet * mult)
            msg = (
                f"🎰 `{line}`\n**JACKPOT!** Three {names[0]} — "
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
        if gif is None:
            await interaction.followup.send(msg)
        else:
            file = discord.File(gif, filename="slots.gif")
            await interaction.followup.send(msg, file=file)

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
            file = view._table_file(hide_dealer=False)
            await interaction.followup.send(embed=embed, view=view, file=file)
            return

        file = view._table_file()
        await interaction.followup.send(embed=view._embed(), view=view, file=file)
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
        try:
            gif = await asyncio.to_thread(roulette_spin_gif, spin)
        except Exception:
            gif = None
        if gif is None:
            await interaction.followup.send(msg)
        else:
            file = discord.File(gif, filename="roulette.gif")
            await interaction.followup.send(msg, file=file)

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
        try:
            gif = await asyncio.to_thread(flip_coin_gif, result)
        except Exception:
            gif = None
        if result == side:
            await econ.add_scrap(interaction.user.id, bet * 2)
            msg = f"It's **{result}**! You win **{bet}** Scrap."
        else:
            msg = f"It's **{result}**. You lose **{bet}** Scrap."
        if gif is None:
            await interaction.followup.send(f"🪙 {msg}")
            return
        file = discord.File(gif, filename="coinflip.gif")
        embed = discord.Embed(description=msg, color=RUST_COLOR)
        embed.set_image(url="attachment://coinflip.gif")
        await interaction.followup.send(file=file, embed=embed)

    # -- crash ------------------------------------------------------------

    @app_commands.command(name="crash", description="Ride the multiplier — cash out before it crashes")
    @app_commands.describe(bet="How much Scrap to bet",
                           cashout="Multiplier to cash out at — 2.0 doubles your bet, 1.5 = 50% profit")
    async def crash(self, interaction: discord.Interaction, bet: int, cashout: float):
        await interaction.response.defer()
        if not await self._take_bet(interaction, bet):
            return
        if cashout < 1.01:
            await interaction.followup.send(
                "❌ Cash-out must be at least **1.01x**.", ephemeral=True
            )
            await _economy(self.bot).add_scrap(interaction.user.id, bet)
            return
        if cashout > 1000:
            await interaction.followup.send(
                "❌ Cash-out can't exceed **1000x**. Try something like 2.0.",
                ephemeral=True,
            )
            await _economy(self.bot).add_scrap(interaction.user.id, bet)
            return
        cashout = round(cashout, 2)

        point = roll_crash_point()
        econ = _economy(self.bot)
        if point >= cashout:
            winnings = int(bet * cashout)
            await econ.add_scrap(interaction.user.id, winnings)
            msg = (
                f"🚀 Cashed out at **{cashout:.2f}x**!\n"
                f"Bet **{bet}** → win **{winnings - bet}** Scrap (total **{winnings}**)."
            )
            color = 0x50FF8C
        else:
            msg = (
                f"💥 **CRASHED at {point:.2f}x!** (aiming for {cashout:.2f}x)\n"
                f"You lose **{bet}** Scrap."
            )
            color = 0xFF4646

        try:
            gif = await asyncio.to_thread(crash_animation_gif, point,
                                          cashout if point >= cashout else None)
        except Exception:
            gif = None
        embed = discord.Embed(title="🚀 CRASH", description=msg, color=color)
        if gif is None:
            await interaction.followup.send(embed=embed)
        else:
            file = discord.File(gif, filename="crash.gif")
            embed.set_image(url="attachment://crash.gif")
            await interaction.followup.send(file=file, embed=embed)

    # -- mines ------------------------------------------------------------

    @app_commands.command(name="mines", description="Reveal tiles, dodge the mines, cash out anytime")
    @app_commands.describe(bet="How much Scrap to bet", mines="Number of mines (1-10)")
    async def mines(self, interaction: discord.Interaction, bet: int, mines: int):
        await interaction.response.defer()
        if not await self._take_bet(interaction, bet):
            return
        if not 1 <= mines <= 10:
            await interaction.followup.send(
                "❌ Mines must be between 1 and 10.", ephemeral=True
            )
            await _economy(self.bot).add_scrap(interaction.user.id, bet)
            return

        mine_positions = set(random.sample(range(25), mines))
        view = MinesView(self.bot, interaction.user.id, bet, mines,
                         mine_positions)
        try:
            img = await asyncio.to_thread(render_mines_board, set(), set())
        except Exception:
            img = None
        embed = discord.Embed(
            title="💣 MINES",
            description=f"**{mines}** mines hidden. Pick tiles to reveal Scrap!\n"
                        f"Bet: **{bet}** Scrap",
            color=RUST_COLOR,
        )
        if img is None:
            await interaction.followup.send(embed=embed, view=view)
        else:
            file = discord.File(img, filename="mines.png")
            embed.set_image(url="attachment://mines.png")
            await interaction.followup.send(file=file, embed=embed, view=view)



    @app_commands.command(name="plinko", description="Drop the chrome ball down the pegs")
    @app_commands.describe(bet="How much Scrap to bet (per ball)",
                           risk="Risk level — higher risk, bigger edge multipliers",
                           balls="How many balls to drop (1-3)")
    @app_commands.choices(risk=[
        app_commands.Choice(name="🟢 Low", value="low"),
        app_commands.Choice(name="🟡 Medium", value="medium"),
        app_commands.Choice(name="🔴 High", value="high"),
    ])
    async def plinko(self, interaction: discord.Interaction, bet: int,
                     risk: app_commands.Choice[str], balls: int = 1):
        await interaction.response.defer()
        if not 1 <= balls <= 3:
            await interaction.followup.send(
                "❌ Balls must be between 1 and 3.", ephemeral=True
            )
            return
        total_bet = bet * balls
        if not await self._take_bet(interaction, total_bet):
            return

        try:
            gif, mults = await asyncio.to_thread(
                plinko_animation_gif, risk.value, balls)
        except Exception:
            gif, mults = None, []

        econ = _economy(self.bot)
        winnings = sum(int(bet * m) for m in mults)
        if winnings > 0:
            await econ.add_scrap(interaction.user.id, winnings)

        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}[risk.value]
        mult_str = " + ".join(f"{m}x" for m in mults)
        profit = winnings - total_bet
        if profit >= 0:
            msg = (f"{risk_emoji} Balls land on **{mult_str}**!\n"
                   f"You win **{profit}** Scrap (total **{winnings}**).")
            color = 0x50FF8C
        else:
            msg = (f"{risk_emoji} Balls land on **{mult_str}**.\n"
                   f"You lose **{-profit}** Scrap.")
            color = 0xFF4646

        embed = discord.Embed(title="⚪ PLINKO", description=msg, color=color)
        embed.add_field(name="Risk", value=risk.name, inline=True)
        embed.add_field(name="Balls", value=str(balls), inline=True)
        embed.add_field(name="Bet", value=f"{total_bet} Scrap", inline=True)
        if gif is None:
            await interaction.followup.send(embed=embed)
        else:
            file = discord.File(gif, filename="plinko.gif")
            embed.set_image(url="attachment://plinko.gif")
            await interaction.followup.send(file=file, embed=embed)

    # -- hi-lo ------------------------------------------------------------

    @app_commands.command(name="hilo", description="Guess higher or lower, build your streak")
    @app_commands.describe(bet="How much Scrap to bet")
    async def hilo(self, interaction: discord.Interaction, bet: int):
        await interaction.response.defer()
        if not await self._take_bet(interaction, bet):
            return

        view = HiLoView(self.bot, interaction.user.id, bet)
        embed, file = view._render()
        await interaction.followup.send(embed=embed, view=view, file=file)
        view.message = await interaction.original_response()

    # -- gamble menu --------------------------------------------------------

    @app_commands.command(name="gamble", description="🎰 Pick a game from the menu — simple gambling")
    async def gamble(self, interaction: discord.Interaction):
        """Show a game picker menu for easy gambling."""
        view = GambleMenu(self)
        embed = discord.Embed(
            title="🎰 Choose Your Game",
            description="Pick a game below, then enter your bet.\nAll the classics, one simple menu.",
            color=RUST_COLOR,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class HiLoView(discord.ui.View):
    """Interactive Hi-Lo: guess higher/lower, cash out anytime."""

    def __init__(self, bot: commands.Bot, user_id: int, bet: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id
        self.bet = bet
        self.current_card = new_card()
        self.streak = 0
        self.multiplier = 1.0
        self.over = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ This isn't your game.", ephemeral=True
            )
            return False
        return True

    def _potential(self) -> int:
        return int(self.bet * self.multiplier)

    def _render(self):
        """Render the current table state."""
        buf = render_hilo_table(
            self.current_card, self.streak, self.multiplier,
            self.bet, self._potential()
        )
        file = discord.File(buf, filename="hilo.png")
        embed = discord.Embed(title="⬆️ Hi-Lo ⬇️", color=0xCE6A2C)
        embed.set_image(url="attachment://hilo.png")
        if not self.over:
            embed.description = (
                f"Current card: **{self.current_card}**\n"
                "Will the next card be higher or lower?"
            )
        return embed, file

    async def _guess(self, interaction: discord.Interaction, guess_high: bool):
        """Handle a higher/lower guess."""
        if self.over:
            return

        new = new_card(exclude=self.current_card)
        old_val = card_value(self.current_card)
        new_val = card_value(new)

        # Tie = push (redraw, streak continues)
        if new_val == old_val:
            self.current_card = new
            embed, file = self._render()
            embed.description = (
                f"Tie! **{new}** — push, try again.\n"
                f"Current card: **{self.current_card}**"
            )
            await interaction.response.edit_message(
                embed=embed, view=self, attachments=[file]
            )
            return

        correct = (new_val > old_val) if guess_high else (new_val < old_val)

        if correct:
            self.streak += 1
            self.multiplier *= 1.4
            self.current_card = new
            embed, file = self._render()
            direction = "higher ⬆️" if guess_high else "lower ⬇️"
            embed.description = (
                f"✅ **{new}** was {direction}! "
                f"Streak: **{self.streak}** ({self.multiplier:.1f}x)\n"
                "Keep going or cash out?"
            )
            await interaction.response.edit_message(
                embed=embed, view=self, attachments=[file]
            )
        else:
            self.over = True
            for child in self.children:
                child.disabled = True
            direction = "higher ⬆️" if guess_high else "lower ⬇️"
            embed, file = self._render()
            embed.description = (
                f"❌ **{new}** was not {direction}. "
                f"You lose **{self.bet}** Scrap."
            )
            embed.color = 0xFF4646
            await interaction.response.edit_message(
                embed=embed, view=self, attachments=[file]
            )

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.success, emoji="⬆️")
    async def higher(self, interaction: discord.Interaction,
                     button: discord.ui.Button):
        await self._guess(interaction, guess_high=True)

    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger, emoji="⬇️")
    async def lower(self, interaction: discord.Interaction,
                    button: discord.ui.Button):
        await self._guess(interaction, guess_high=False)

    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.primary, emoji="💰")
    async def cash_out(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        if self.over:
            return
        self.over = True
        for child in self.children:
            child.disabled = True

        winnings = self._potential()
        profit = winnings - self.bet
        if winnings > 0:
            await self.bot.economy.add_scrap(self.user_id, winnings)

        embed, file = self._render()
        if profit > 0:
            embed.description = (
                f"💰 Cashed out! You win **{profit}** Scrap "
                f"(total **{winnings}**)."
            )
            embed.color = 0x50FF8C
        else:
            embed.description = "Cashed out — bet returned."
        await interaction.response.edit_message(
            embed=embed, view=self, attachments=[file]
        )

    async def on_timeout(self):
        if self.over:
            return
        self.over = True
        for child in self.children:
            child.disabled = True
        # Auto cash out on timeout
        winnings = self._potential()
        if winnings > 0:
            await self.bot.economy.add_scrap(self.user_id, winnings)
        if self.message is not None:
            try:
                embed, file = self._render()
                embed.description = "⏰ Time expired — auto cashed out."
                await self.message.edit(embed=embed, view=self,
                                        attachments=[file])
            except discord.HTTPException:
                pass


class MinesView(discord.ui.View):
    """Interactive Mines board: pick tiles via select menu, cash out anytime."""

    def __init__(self, bot: commands.Bot, user_id: int, bet: int, mines: int,
                 mine_positions: set[int]):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.bet = bet
        self.mine_positions = mine_positions
        self.revealed: set[int] = set()
        self.over = False

    def _econ(self) -> EconomyService:
        return _economy(self.bot)

    def _mult(self) -> float:
        return mines_multiplier(len(self.mine_positions), len(self.revealed))

    async def _render(self) -> tuple[discord.Embed, discord.File | None]:
        try:
            img = await asyncio.to_thread(
                render_mines_board, self.revealed, self.mine_positions,
                self.over)
        except Exception:
            img = None
        mult = self._mult()
        potential = int(self.bet * mult)
        embed = discord.Embed(
            title="💣 MINES",
            description=f"Revealed: **{len(self.revealed)}** | "
                        f"Multiplier: **{mult:.2f}x**\n"
                        f"Potential win: **{potential}** Scrap",
            color=RUST_COLOR,
        )
        if img is None:
            return embed, None
        file = discord.File(img, filename="mines.png")
        embed.set_image(url="attachment://mines.png")
        return embed, file

    @discord.ui.select(
        placeholder="Pick a tile (1-25)...",
        options=[discord.SelectOption(label=f"Tile {i+1}", value=str(i))
                 for i in range(25)],
    )
    async def pick_tile(self, interaction: discord.Interaction,
                        select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ This isn't your game!", ephemeral=True)
            return
        if self.over:
            await interaction.response.send_message(
                "❌ Game is over.", ephemeral=True)
            return
        idx = int(select.values[0])
        if idx in self.revealed:
            await interaction.response.send_message(
                "❌ Tile already revealed.", ephemeral=True)
            return

        await interaction.response.defer()
        self.revealed.add(idx)

        if idx in self.mine_positions:
            # Boom.
            self.over = True
            for child in self.children:
                child.disabled = True
            embed, file = await self._render()
            embed.title = "💥 BOOM!"
            embed.description = (
                f"You hit a mine!\nYou lose **{self.bet}** Scrap."
            )
            embed.color = 0xFF4646
            if file:
                await interaction.followup.send(embed=embed, file=file,
                                                view=self)
            else:
                await interaction.followup.send(embed=embed, view=self)
            self.stop()
            return

        # Safe — update the board.
        mult = self._mult()
        embed, file = await self._render()
        if file:
            await interaction.followup.send(
                f"✅ Safe! Multiplier now **{mult:.2f}x**",
                embed=embed, file=file, view=self, ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ Safe! Multiplier now **{mult:.2f}x**",
                embed=embed, view=self, ephemeral=True)

    @discord.ui.button(label="💰 Cash Out", style=discord.ButtonStyle.success)
    async def cash_out(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ This isn't your game!", ephemeral=True)
            return
        if self.over:
            await interaction.response.send_message(
                "❌ Game is over.", ephemeral=True)
            return
        if not self.revealed:
            await interaction.response.send_message(
                "❌ Reveal at least one tile first!", ephemeral=True)
            return

        await interaction.response.defer()
        self.over = True
        for child in self.children:
            child.disabled = True
        mult = self._mult()
        winnings = int(self.bet * mult)
        await self._econ().add_scrap(self.user_id, winnings)
        embed, file = await self._render()
        embed.title = "💰 Cashed Out!"
        embed.description = (
            f"**{mult:.2f}x** multiplier!\n"
            f"You win **{winnings - self.bet}** Scrap (total **{winnings}**)."
        )
        embed.color = 0x50FF8C
        if file:
            await interaction.followup.send(embed=embed, file=file, view=self)
        else:
            await interaction.followup.send(embed=embed, view=self)
        self.stop()

    # -- plinko -----------------------------------------------------------


class GambleGameSelect(discord.ui.Select):
    """Dropdown to pick which casino game to play."""

    def __init__(self, casino: "Casino"):
        self.casino = casino
        options = [
            discord.SelectOption(label="Slots", value="slots", emoji="🎰",
                                 description="Spin the 3-reel slot machine"),
            discord.SelectOption(label="Blackjack", value="blackjack", emoji="🃏",
                                 description="Beat the dealer, pays 3:2"),
            discord.SelectOption(label="Roulette", value="roulette", emoji="🎡",
                                 description="Bet red/black or a number"),
            discord.SelectOption(label="Coinflip", value="coinflip", emoji="🪙",
                                 description="Heads or tails, double or nothing"),
            discord.SelectOption(label="Crash", value="crash", emoji="📈",
                                 description="Ride the multiplier, cash out in time"),
            discord.SelectOption(label="Mines", value="mines", emoji="💣",
                                 description="Dodge the mines, stack the multiplier"),
            discord.SelectOption(label="Plinko", value="plinko", emoji="🎯",
                                 description="Drop balls, hit big multipliers"),
            discord.SelectOption(label="Hi-Lo", value="hilo", emoji="🔼",
                                 description="Higher or lower? 1.4x per win"),
        ]
        super().__init__(placeholder="Pick a game...", options=options)

    async def callback(self, interaction: discord.Interaction):
        game = self.values[0]
        # Show bet modal for the chosen game
        modal = GambleBetModal(self.casino, game)
        await interaction.response.send_modal(modal)


class GambleMenu(discord.ui.View):
    """Game picker menu for /gamble."""

    def __init__(self, casino: "Casino"):
        super().__init__(timeout=120)
        self.add_item(GambleGameSelect(casino))


class GambleBetModal(discord.ui.Modal):
    """Bet amount input after picking a game."""

    def __init__(self, casino: "Casino", game: str):
        super().__init__(title=f"Bet on {game.title()}")
        self.casino = casino
        self.game = game
        self.bet_input = discord.ui.TextInput(
            label="Bet amount (Scrap)",
            placeholder="e.g. 100",
            required=True,
            max_length=10,
        )
        self.add_item(self.bet_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Bet must be a whole number.", ephemeral=True)
            return
        if bet <= 0:
            await interaction.response.send_message(
                "❌ Bet must be positive.", ephemeral=True)
            return

        casino = self.casino
        game = self.game

        # Simple games: launch directly with just the bet
        if game in ("slots", "blackjack", "hilo"):
            await interaction.response.defer()
            # Delegate to the existing command logic
            if game == "slots":
                await casino.slots.callback(casino, interaction, bet)
            elif game == "blackjack":
                await casino.blackjack.callback(casino, interaction, bet)
            elif game == "hilo":
                await casino.hilo.callback(casino, interaction, bet)
            return

        # Games needing a choice: show follow-up buttons
        await interaction.response.defer(ephemeral=True)
        if game == "roulette":
            view = GambleRouletteChoice(casino, bet)
            await interaction.followup.send(
                f"🎡 **Roulette** — bet **{bet}** Scrap. Red or black?",
                view=view, ephemeral=True)
        elif game == "coinflip":
            view = GambleCoinflipChoice(casino, bet)
            await interaction.followup.send(
                f"🪙 **Coinflip** — bet **{bet}** Scrap. Heads or tails?",
                view=view, ephemeral=True)
        elif game == "crash":
            view = GambleCrashChoice(casino, bet)
            await interaction.followup.send(
                f"📈 **Crash** — bet **{bet}** Scrap. When to cash out?",
                view=view, ephemeral=True)
        elif game == "mines":
            view = GambleMinesChoice(casino, bet)
            await interaction.followup.send(
                f"💣 **Mines** — bet **{bet}** Scrap. How many mines?",
                view=view, ephemeral=True)
        elif game == "plinko":
            # Plinko defaults: medium risk, 1 ball — simple path
            risk_choice = app_commands.Choice(name="Medium", value="medium")
            await casino.plinko.callback(casino, interaction, bet, risk_choice, 1)


class GambleRouletteChoice(discord.ui.View):
    def __init__(self, casino: "Casino", bet: int):
        super().__init__(timeout=60)
        self.casino = casino
        self.bet = bet

    @discord.ui.button(label="🔴 Red", style=discord.ButtonStyle.danger)
    async def red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await self.casino.roulette.callback(self.casino, interaction, self.bet, "red")
        self.stop()

    @discord.ui.button(label="⚫ Black", style=discord.ButtonStyle.secondary)
    async def black(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await self.casino.roulette.callback(self.casino, interaction, self.bet, "black")
        self.stop()


class GambleCoinflipChoice(discord.ui.View):
    def __init__(self, casino: "Casino", bet: int):
        super().__init__(timeout=60)
        self.casino = casino
        self.bet = bet

    @discord.ui.button(label="Heads", style=discord.ButtonStyle.primary)
    async def heads(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await self.casino.coinflip.callback(self.casino, interaction, self.bet, "heads")
        self.stop()

    @discord.ui.button(label="Tails", style=discord.ButtonStyle.secondary)
    async def tails(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await self.casino.coinflip.callback(self.casino, interaction, self.bet, "tails")
        self.stop()


class GambleCrashChoice(discord.ui.View):
    def __init__(self, casino: "Casino", bet: int):
        super().__init__(timeout=60)
        self.casino = casino
        self.bet = bet

    async def _pick(self, interaction: discord.Interaction, cashout: float):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await self.casino.crash.callback(self.casino, interaction, self.bet, cashout)
        self.stop()

    @discord.ui.button(label="1.5x", style=discord.ButtonStyle.secondary)
    async def c15(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 1.5)

    @discord.ui.button(label="2x", style=discord.ButtonStyle.primary)
    async def c2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 2.0)

    @discord.ui.button(label="5x", style=discord.ButtonStyle.danger)
    async def c5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 5.0)

    @discord.ui.button(label="10x", style=discord.ButtonStyle.danger)
    async def c10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 10.0)


class GambleMinesChoice(discord.ui.View):
    def __init__(self, casino: "Casino", bet: int):
        super().__init__(timeout=60)
        self.casino = casino
        self.bet = bet

    async def _pick(self, interaction: discord.Interaction, mines: int):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        await self.casino.mines.callback(self.casino, interaction, self.bet, mines)
        self.stop()

    @discord.ui.button(label="1 mine", style=discord.ButtonStyle.secondary)
    async def m1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 1)

    @discord.ui.button(label="3 mines", style=discord.ButtonStyle.primary)
    async def m3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 3)

    @discord.ui.button(label="5 mines", style=discord.ButtonStyle.danger)
    async def m5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 5)

    @discord.ui.button(label="10 mines", style=discord.ButtonStyle.danger)
    async def m10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, 10)



async def setup(bot: commands.Bot):
    await bot.add_cog(Casino(bot))
