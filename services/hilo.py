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


def _transparent_bg(img: Image.Image) -> Image.Image:
    """Make the dark background surround transparent so the image blends
    seamlessly into Discord's chat."""
    import numpy as np
    img = img.convert("RGBA")
    arr = np.array(img)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    dark = (r < 55) & (g < 55) & (b < 55)
    not_green = g < r + 20  # preserve the table felt
    mask = dark & not_green
    arr[mask, 3] = 0  # fully transparent
    return Image.fromarray(arr)


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
    """Render the Hi-Lo table: photorealistic casino table, card with shadow."""
    W, H = 600, 500

    # Photorealistic table background
    bg_path = os.path.join(_ASSETS, "hilo_bg.png")
    if os.path.exists(bg_path):
        table = Image.open(bg_path).convert("RGB").resize((W, H), Image.LANCZOS)
        # Make the dark surround transparent so it blends into Discord.
        table = _transparent_bg(table)
    else:
        table = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(table)

    # Title with gold
    font_title = _font(30)
    title = "HI-LO"
    tb = d.textbbox((0, 0), title, font=font_title)
    tw = tb[2] - tb[0]
    # Dark outline for readability
    tx, ty = (W - tw) / 2 - tb[0], 28 - tb[1]
    for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
        d.text((tx + ox, ty + oy), title, font=font_title, fill=(0, 0, 0))
    d.text((tx, ty), title, font=font_title, fill=(255, 215, 0))

    # Current card with drop shadow
    card_img = draw_card(current_card)
    # Slightly larger card for presence
    card_img = card_img.resize((int(CARD_W * 1.2), int(CARD_H * 1.2)), Image.LANCZOS)
    cw, ch = card_img.size
    cx = (W - cw) // 2
    cy = 110

    # Drop shadow
    shadow = Image.new("RGBA", (cw + 20, ch + 20), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([10, 10, cw + 10, ch + 10], radius=12, fill=(0, 0, 0, 120))
    shadow = shadow.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(8))
    table.paste(shadow, (cx - 10, cy - 10), shadow)
    table.paste(card_img, (cx, cy))

    # Stats with outline for readability
    font_stat = _font(22)
    y = cy + ch + 25
    stats = [
        f"Streak: {streak}  |  Multiplier: {multiplier:.1f}x",
        f"Potential: {potential} Scrap  (Bet: {bet})",
    ]
    for i, txt in enumerate(stats):
        tb = d.textbbox((0, 0), txt, font=font_stat)
        tw = tb[2] - tb[0]
        sx, sy = (W - tw) / 2 - tb[0], y + i * 36 - tb[1]
        for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            d.text((sx + ox, sy + oy), txt, font=font_stat, fill=(0, 0, 0))
        d.text((sx, sy), txt, font=font_stat, fill=(255, 255, 255))

    buf = io.BytesIO()
    table.save(buf, format="PNG")
    buf.seek(0)
    return buf
