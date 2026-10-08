"""Photorealistic blackjack table renderer."""
import io
import os

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))

# Card dimensions (poker size ratio).
CARD_W, CARD_H = 120, 168
# Positions on the table (fractions).
DEALER_POS = (0.5, 0.28)  # center-x, y for dealer hand
PLAYER_POS = (0.5, 0.72)  # center-x, y for player hand


def _font(size: int) -> ImageFont.FreeTypeFont:
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    return ImageFont.load_default()


def _draw_card(rank: str, suit: str, face_down: bool = False) -> Image.Image:
    """Draw a single playing card."""
    card = Image.new("RGB", (CARD_W, CARD_H), (245, 245, 240))
    d = ImageDraw.Draw(card)
    # Rounded corners (approximate with rectangle + border).
    d.rectangle([0, 0, CARD_W - 1, CARD_H - 1], outline=(180, 180, 170), width=3)

    if face_down:
        # Card back: deep purple pattern.
        d.rectangle([8, 8, CARD_W - 9, CARD_H - 9], fill=(75, 20, 120))
        d.rectangle([12, 12, CARD_W - 13, CARD_H - 13], outline=(180, 150, 255), width=2)
        # Diamond pattern.
        for y in range(20, CARD_H - 20, 16):
            for x in range(20, CARD_W - 20, 16):
                d.polygon([(x, y - 5), (x + 5, y), (x, y + 5), (x - 5, y)],
                          outline=(150, 120, 220))
    else:
        # Rank and suit.
        is_red = suit in ("♥️", "♦️")
        color = (180, 20, 30) if is_red else (30, 30, 30)
        # Simplify suit emoji to character.
        suit_char = {"♠️": "♠", "♥️": "♥", "♦️": "♦", "♣️": "♣"}.get(suit, suit)
        font_large = _font(48)
        font_small = _font(28)
        # Top-left rank + suit.
        d.text((10, 8), rank, font=font_small, fill=color)
        d.text((10, 36), suit_char, font=font_small, fill=color)
        # Center suit (large).
        tb = d.textbbox((0, 0), suit_char, font=font_large)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        d.text(((CARD_W - tw) / 2 - tb[0], (CARD_H - th) / 2 - tb[1]),
               suit_char, font=font_large, fill=color)
        # Bottom-right (rotated).
        d.text((CARD_W - 32, CARD_H - 62), rank, font=font_small, fill=color)
        d.text((CARD_W - 32, CARD_H - 34), suit_char, font=font_small, fill=color)

    return card


# Transparent background mode — set to False to use Discord's bg color instead.
# Backup of the Discord-bg version: services/blackjack.py.discordbg-backup
USE_TRANSPARENT_BG = True


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


# Discord dark theme chat background — used to make game images blend in.
DISCORD_BG = (49, 51, 56)  # #313338


def _discord_bg(img: Image.Image) -> Image.Image:
    """Replace near-black background pixels with Discord's chat background
    color so rendered game images look seamless in Discord."""
    import numpy as np
    arr = np.array(img)
    # Replace dark background surround with Discord's chat color.
    # Only targets pixels that are dark AND not green-dominant (so the
    # table felt, which is greenish, is preserved).
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    dark = (r < 55) & (g < 55) & (b < 55)
    not_green = g < r + 20  # table felt has g well above r
    mask = dark & not_green
    arr[mask] = DISCORD_BG
    return Image.fromarray(arr)


def render_blackjack_table(player: list[str], dealer: list[str],
                           hide_dealer: bool = True) -> io.BytesIO:
    """Render the blackjack table with cards. player/dealer are lists like
    ['A♠️', 'K♥️']. Returns PNG bytes."""
    table = Image.open(os.path.join(_ASSETS, "blackjack_table.png")).convert("RGB")
    # Blend into Discord: transparent background (or Discord's bg color
    # if USE_TRANSPARENT_BG is False) so the image looks seamless.
    if USE_TRANSPARENT_BG:
        table = _transparent_bg(table)
    else:
        table = _discord_bg(table)
    W, H = table.size

    def parse(card_str: str) -> tuple[str, str]:
        # Card strings are like "A♠️" where suit is 2 chars (emoji + variation selector).
        if card_str.endswith("️"):
            return card_str[:-2], card_str[-2:]
        return card_str[:-1], card_str[-1:]

    # Dealer hand (top).
    dx, dy = int(DEALER_POS[0] * W), int(DEALER_POS[1] * H)
    for i, c in enumerate(dealer):
        rank, suit = parse(c)
        face_down = hide_dealer and i == 1
        card = _draw_card(rank, suit, face_down)
        # Slight fan.
        x = dx - (len(dealer) * (CARD_W + 10)) // 2 + i * (CARD_W + 10)
        table.paste(card, (x, dy - CARD_H // 2))

    # Player hand (bottom).
    px, py = int(PLAYER_POS[0] * W), int(PLAYER_POS[1] * H)
    for i, c in enumerate(player):
        rank, suit = parse(c)
        card = _draw_card(rank, suit, False)
        x = px - (len(player) * (CARD_W + 10)) // 2 + i * (CARD_W + 10)
        table.paste(card, (x, py - CARD_H // 2))

    # Scale for Discord.
    small = table.resize((600, int(600 * H / W)), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    buf.seek(0)
    return buf
