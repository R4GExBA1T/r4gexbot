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
    """Build one face of a real gold coin: photo texture, embossed icon."""
    S = COIN_R * 2
    cx = cy = COIN_R

    # Real brushed-gold photo texture, masked to the coin disc.
    tex = Image.open(os.path.join(_ASSETS, "gold_texture.png")).convert("RGB")
    tex = tex.resize((S, S), Image.LANCZOS)
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, S, S], fill=255)
    face = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    face.paste(tex, (0, 0), mask)

    d = ImageDraw.Draw(face)
    # Darken the edge for depth (vignette).
    for r in range(COIN_R, int(COIN_R * 0.82), -2):
        alpha = int(150 * (COIN_R - r) / (COIN_R * 0.18))
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=(60, 40, 15, min(alpha, 150)), width=2)

    # Reeded edge.
    for i in range(72):
        a = math.radians(i * 5)
        x1, y1 = cx + (COIN_R - 1) * math.cos(a), cy + (COIN_R - 1) * math.sin(a)
        x2, y2 = cx + (COIN_R - 9) * math.cos(a), cy + (COIN_R - 9) * math.sin(a)
        d.line([x1, y1, x2, y2], fill=(90, 65, 25, 200), width=2)
    d.ellipse([0, 0, S, S], outline=(75, 55, 22, 255), width=4)

    # Item icon, embossed into the gold.
    icon = Image.open(icon_path).convert("RGBA")
    icon_size = int(S * 0.56)
    icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
    ix, iy = int((S - icon_size) / 2), int((S - icon_size) / 2) - 10
    # Soft dark halo behind the icon to seat it in the metal.
    halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse([ix - 6, iy - 6, ix + icon_size + 6, iy + icon_size + 6],
               fill=(50, 35, 12, 110))
    face.alpha_composite(halo)
    face.alpha_composite(icon, (ix, iy))

    # Label engraved at the bottom.
    font = _font(22)
    tb = d.textbbox((0, 0), label, font=font)
    lx, ly = (S - (tb[2] - tb[0])) / 2, S - 44
    d.text((lx + 1, ly + 2), label, font=font, fill=(255, 240, 200, 220))
    d.text((lx, ly), label, font=font, fill=(65, 45, 18, 255))
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
