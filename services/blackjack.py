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


def render_blackjack_table(player: list[str], dealer: list[str],
                           hide_dealer: bool = True) -> io.BytesIO:
    """Render the blackjack table with cards. player/dealer are lists like
    ['A♠️', 'K♥️']. Returns PNG bytes."""
    table = Image.open(os.path.join(_ASSETS, "blackjack_table.png")).convert("RGB")
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
