"""Coin flip GIF generator for /coinflip.

A detailed metal coin flips on its vertical axis: heads shows the Metal
Facemask, tails shows the Road Sign Kilt. Spins fast, eases out, and lands
on the winning face. Plays once — no loop.
"""

from __future__ import annotations

import io
import math
import os

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(__file__)

SIZE = 220          # GIF dimensions
COIN_R = 90         # coin radius
BG = (14, 10, 16)
GOLD = (212, 175, 55)
GOLD_DARK = (140, 110, 30)
BRONZE = (160, 120, 60)


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _make_coin_face(icon_path: str, label: str) -> Image.Image:
    """Build one face of the coin: metallic disc + item icon + label."""
    S = COIN_R * 2
    face = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(face)

    # Metallic gold disc with radial-ish shading (concentric circles).
    for r in range(COIN_R, 0, -2):
        shade = int(140 + 70 * (r / COIN_R))  # darker edge, brighter center
        color = (min(shade + 40, 230), min(shade, 190), max(shade - 80, 60))
        d.ellipse([COIN_R - r, COIN_R - r, COIN_R + r, COIN_R + r], fill=color)
    # Rim.
    d.ellipse([0, 0, S, S], outline=GOLD_DARK, width=8)
    d.ellipse([8, 8, S - 8, S - 8], outline=(230, 200, 120), width=2)

    # Item icon centered.
    icon = Image.open(icon_path).convert("RGBA")
    icon_size = int(S * 0.58)
    icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
    face.alpha_composite(icon, (int((S - icon_size) / 2), int((S - icon_size) / 2) - 8))

    # Label at the bottom.
    font = _font(22)
    tb = d.textbbox((0, 0), label, font=font)
    d.text(((S - (tb[2] - tb[0])) / 2, S - 42), label, font=font,
           fill=(60, 40, 10))
    return face


def flip_coin_gif(winner: str, frames: int = 22) -> io.BytesIO:
    """Render the flip. winner: 'heads' | 'tails'. Plays once, lands on winner."""
    heads = _make_coin_face(os.path.join(_ASSETS, "coin_heads.png"), "HEADS")
    tails = _make_coin_face(os.path.join(_ASSETS, "coin_tails.png"), "TAILS")

    # Final flip angle: 0° = heads facing viewer, 180° = tails.
    target = 0 if winner == "heads" else 180
    total_deg = 3 * 360 + target  # 3 full flips, then land

    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        eased = 1 - (1 - t) ** 3
        angle = total_deg * eased
        # Horizontal squash simulates the 3D flip.
        scale_x = abs(math.cos(math.radians(angle)))
        scale_x = max(scale_x, 0.06)  # never fully vanish
        face = heads if math.cos(math.radians(angle)) >= 0 else tails

        W = max(int(face.width * scale_x), 2)
        squashed = face.resize((W, face.height), Image.LANCZOS)

        frame = Image.new("RGB", (SIZE, SIZE), BG)
        # Slight vertical bob during the flip.
        bob = int(10 * math.sin(math.radians(angle * 2)) * (1 - t))
        frame.paste(squashed, (int((SIZE - W) / 2), int((SIZE - face.height) / 2) - bob),
                    squashed)
        out_frames.append(frame)

    # Hold the winning face.
    out_frames.extend([out_frames[-1]] * 10)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=70)
    buf.seek(0)
    return buf
