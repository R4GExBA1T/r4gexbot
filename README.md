# Ximmy 🎰

A Rust-themed Discord casino bot. Virtual **Scrap** currency, daily wheel
spins, streaks, and a full casino: slots, blackjack, roulette, coinflip.

## Commands

| Command | What it does |
|---|---|
| `/daily` | Spin the daily wheel (24h cooldown). Weighted payouts: 10–50 (common), 100, 250, 1000 jackpot (~1%). Streak bonus +10%/day, capped +70% |
| `/weekly` | 500 Scrap every 7 days (+ streak bonus if your daily streak ≥ 5) |
| `/balance` | Your Scrap balance |
| `/leaderboard` | Top 10 richest members |
| `/give @member <amount>` | Send Scrap to someone (no self-gifting) |
| `/slots <bet>` | 3-reel slots. Triples pay 10x (💎 15x, 7️⃣ 20x), pairs pay 2x |
| `/blackjack <bet>` | Blackjack vs dealer with Hit/Stand buttons. Dealer stands on 17, blackjack pays 3:2 |
| `/roulette <bet> <choice>` | European wheel. `red`/`black` pays 2x, a number 0–36 pays 36x |
| `/coinflip <bet> <heads\|tails>` | Double or nothing |
| `/linkrust <gamertag>` | Link your Xbox gamertag / PSN ID (for future Rust Console server rewards) |
| `/unlinkrust` | Remove the link |

New members start with **100 Scrap** on first use. All bets are validated
(positive integers, can't exceed your balance).

## Setup

1. **Python 3.11+**, then install deps:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a bot at https://discord.com/developers/applications → **Bot** →
   **Reset Token** → copy it. Enable the **applications.commands** scope when
   inviting (OAuth2 URL Generator, no privileged intents needed).
3. Bot permissions needed in your server: **Send Messages**, **Embed Links**,
   **Use Slash Commands** (shown as "Use Application Commands").
4. Copy `.env.example` to `.env` and paste your token:
   ```bash
   cp .env.example .env
   # edit .env: DISCORD_TOKEN=your-token-here
   ```
5. Run:
   ```bash
   python bot.py
   ```
   Slash commands sync automatically on startup (`setup_hook`). Global sync
   can take up to ~1 hour to appear everywhere; for instant testing, sync to
   one guild instead (see below).

### Instant command sync for testing

In `bot.py`'s `setup_hook`, replace `await self.tree.sync()` with:
```python
guild = discord.Object(id=YOUR_SERVER_ID)
self.tree.copy_global_to(guild=guild)
await self.tree.sync(guild=guild)
```

## Architecture
<!-- trigger railway redeploy -->


```
ximmy-bot/
├── bot.py                  # entrypoint, loads cogs, syncs commands
├── services/
│   └── economy.py          # THE economy: all balance logic lives here
├── cogs/
│   ├── economy.py          # /daily /weekly /balance /leaderboard /give /linkrust
│   └── casino.py           # /slots /blackjack /roulette /coinflip
```

**Rule: cogs never touch SQL.** Everything goes through
`services/economy.py` (`get_balance`, `add_scrap`, `deduct_scrap`,
`transfer`, `claim_daily`, `claim_weekly`, ...). Cooldowns are
computed from timestamps in SQLite (`ximmy.db`, created next to `bot.py`),
so restarts never lose or reset state. All virtual currency: no real money
is wagered, won, or lost, and nothing links to Steam — `/linkrust` stores
a member's Xbox gamertag / PSN ID for future Rust Console server rewards.

## Running 24/7

For production, run under a process manager (systemd, pm2, or a host like
Railway/Render). The SQLite DB file `ximmy.db` must persist — back it up
regularly. All virtual currency: no real money is wagered, won, or lost.
