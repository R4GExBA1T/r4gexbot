"""Hi-Lo: guess if the next card is higher or lower. Streak multiplier, cash out anytime."""
import io
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANK_VALUES = {r: i for i, r in enumerate(RANKS)}

CARD_W, CARD_H = 140, 196


def _font(size: int) -> ImageFont.FreeTypeFont:
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    return ImageFont.load_default()


def draw_card(card: str) -> Image.Image:
    """Draw a single playing card. Card format like 'QH', '10S'."""
    # Parse: rank is all but last char, suit is last char
    # Our format: "Q♥️" etc. from RANKS + SUITS
    rank = card[:-2]
    suit = card[-2:]
    is_red = suit in ("♥️", "♦️")
    color = (200, 30, 30) if is_red else (30, 30, 30)

    img = Image.new("RGB", (CARD_W, CARD_H), (245, 245, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, CARD_W - 1, CARD_H - 1], outline=(180, 180, 170), width=3)

    font_big = _font(48)
    font_small = _font(28)

    # Center rank + suit
    txt = f"{rank}\n{suit}"
    # Draw rank and suit centered
    tb = d.multiline_textbbox((0, 0), txt, font=font_big, align="center")
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    d.multiline_text(((CARD_W - tw) / 2 - tb[0], (CARD_H - th) / 2 - tb[1]),
                     txt, font=font_big, fill=color, align="center")

    # Corner indices
    d.text((10, 8), rank, font=font_small, fill=color)
    d.text((10, 36), suit, font=font_small, fill=color)

    return img


def new_card(exclude: str | None = None) -> str:
    """Draw a random card, optionally excluding one."""
    while True:
        card = f"{random.choice(RANKS)}{random.choice(SUITS)}"
        if card != exclude:
            return card


def card_value(card: str) -> int:
    rank = card[:-2]
    return RANK_VALUES[rank]


def render_hilo_table(current_card: str, streak: int, multiplier: float,
                      bet: int, potential: int) -> io.BytesIO:
    """Render the Hi-Lo table: current card, streak, multiplier, potential win."""
    W, H = 500, 420
    # Dark green felt
    table = Image.new("RGB", (W, H), (20, 80, 40))
    d = ImageDraw.Draw(table)

    # Felt texture (subtle noise)
    for _ in range(800):
        x, y = random.randint(0, W - 1), random.randint(0, H - 1)
        shade = random.randint(-8, 8)
        r, g, b = 20 + shade, 80 + shade, 40 + shade
        d.point((x, y), fill=(max(0, r), max(0, g), max(0, b)))

    # Gold border
    d.rectangle([8, 8, W - 9, H - 9], outline=(180, 150, 80), width=3)

    # Title
    font_title = _font(28)
    title = "⬆️ HI-LO ⬇️"
    tb = d.textbbox((0, 0), title, font=font_title)
    tw = tb[2] - tb[0]
    d.text(((W - tw) / 2 - tb[0], 20 - tb[1]), title,
           font=font_title, fill=(255, 215, 0))

    # Current card in center
    card_img = draw_card(current_card)
    cx = (W - CARD_W) // 2
    cy = 100
    table.paste(card_img, (cx, cy))

    # Stats below card
    font_stat = _font(20)
    y = cy + CARD_H + 20

    stats = [
        f"Streak: {streak}  |  Multiplier: {multiplier:.1f}x",
        f"Potential: {potential} Scrap  (Bet: {bet})",
    ]
    for i, txt in enumerate(stats):
        tb = d.textbbox((0, 0), txt, font=font_stat)
        tw = tb[2] - tb[0]
        d.text(((W - tw) / 2 - tb[0], y + i * 32 - tb[1]),
               txt, font=font_stat, fill=(255, 255, 255))

    buf = io.BytesIO()
    table.save(buf, format="PNG")
    buf.seek(0)
    return buf
