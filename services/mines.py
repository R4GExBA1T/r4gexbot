"""Hyper-realistic Mines game: 5x5 grid of Rust metal tiles."""
import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))
GRID = 5
TILE = 96
GAP = 6


def _font(size: int) -> ImageFont.FreeTypeFont:
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    return ImageFont.load_default()


def _load_tiles():
    back = Image.open(os.path.join(_ASSETS, "mines_back.png")).convert("RGB")
    safe = Image.open(os.path.join(_ASSETS, "mines_safe.png")).convert("RGB")
    mine = Image.open(os.path.join(_ASSETS, "mines_mine.png")).convert("RGB")
    return (back.resize((TILE, TILE), Image.LANCZOS),
            safe.resize((TILE, TILE), Image.LANCZOS),
            mine.resize((TILE, TILE), Image.LANCZOS))


def mines_multiplier(mines: int, revealed: int) -> float:
    """Standard mines multiplier with 3% house edge."""
    total = GRID * GRID
    mult = 1.0
    for i in range(revealed):
        mult *= (total - i) / (total - mines - i)
    return round(mult * 0.97, 2)


def render_mines_board(revealed: set[int], mines: set[int],
                       game_over: bool = False) -> io.BytesIO:
    """Render the 5x5 board. revealed: indices the player opened.
    mines: mine positions (only shown when game_over)."""
    back, safe, mine = _load_tiles()
    size = GRID * TILE + (GRID + 1) * GAP
    # Transparent background so it blends into Discord's chat.
    board = Image.new("RGBA", (size, size + 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(board)

    for idx in range(GRID * GRID):
        r, c = divmod(idx, GRID)
        x = GAP + c * (TILE + GAP)
        y = GAP + r * (TILE + GAP)
        if idx in revealed:
            tile = mine if idx in mines else safe
        elif game_over and idx in mines:
            tile = mine
        else:
            tile = back
        board.paste(tile, (x, y))
        # Number label for unrevealed tiles (so players can pick).
        if idx not in revealed and not (game_over and idx in mines):
            font = _font(22)
            txt = str(idx + 1)
            tb = d.textbbox((0, 0), txt, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            # Small dark pill in the corner.
            px, py = x + 6, y + 6
            d.rounded_rectangle([px, py, px + tw + 12, py + th + 8],
                                radius=8, fill=(0, 0, 0, 180))
            d.text((px + 6 - tb[0], py + 4 - tb[1]), txt, font=font,
                   fill=(255, 255, 255))

    # Footer bar.
    font = _font(24)
    d.text((GAP, size + 18), "Pick a tile number, or Cash Out",
           font=font, fill=(200, 200, 200))

    buf = io.BytesIO()
    board.save(buf, format="PNG")
    buf.seek(0)
    return buf
