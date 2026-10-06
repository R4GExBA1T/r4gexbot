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
    """Build one face of an old gold coin: aged metal, reeded edge, patina."""
    import random
    S = COIN_R * 2
    face = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(face)
    cx = cy = COIN_R

    # Aged gold: radial gradient, bright warm center -> dark bronze edge.
    for r in range(COIN_R, 0, -1):
        t = r / COIN_R  # 1 at edge, 0 at center
        rr = int(232 - 90 * t)
        gg = int(196 - 90 * t)
        bb = int(120 - 70 * t)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(rr, gg, bb))

    # Metal grain: subtle noise for a worn look.
    rng = random.Random(7)
    for _ in range(900):
        a = rng.uniform(0, 6.283)
        rad = rng.uniform(0, COIN_R * 0.95)
        x, y = int(cx + rad * math.cos(a)), int(cy + rad * math.sin(a))
        v = rng.randint(-14, 14)
        d.point((x, y), fill=(180 + v, 150 + v, 95 + v))

    # Patina: faint tarnish, very subtle.
    for _ in range(8):
        a = rng.uniform(0, 6.283)
        rad = rng.uniform(COIN_R * 0.4, COIN_R * 0.85)
        x, y = cx + rad * math.cos(a), cy + rad * math.sin(a)
        pr = rng.randint(3, 8)
        d.ellipse([x - pr, y - pr, x + pr, y + pr], fill=(150, 120, 70, 45))

    # Reeded edge: fine ridges around the rim like a real coin.
    for i in range(72):
        a = math.radians(i * 5)
        x1, y1 = cx + (COIN_R - 2) * math.cos(a), cy + (COIN_R - 2) * math.sin(a)
        x2, y2 = cx + (COIN_R - 10) * math.cos(a), cy + (COIN_R - 10) * math.sin(a)
        d.line([x1, y1, x2, y2], fill=(95, 70, 30), width=2)
    d.ellipse([0, 0, S, S], outline=(80, 58, 25), width=5)
    d.ellipse([10, 10, S - 10, S - 10], outline=(245, 220, 150), width=2)

    # Item icon, embossed: dark drop shadow offset, then the icon.
    icon = Image.open(icon_path).convert("RGBA")
    icon_size = int(S * 0.56)
    icon = icon.resize((icon_size, icon_size), Image.LANCZOS)
    ix, iy = int((S - icon_size) / 2), int((S - icon_size) / 2) - 10
    shadow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    shadow_mask = icon.split()[3].point(lambda v: int(v * 0.55))
    shadow.paste((40, 28, 12), (3, 4), shadow_mask)
    face.alpha_composite(shadow, (ix, iy))
    face.alpha_composite(icon, (ix, iy))

    # Label engraved at the bottom.
    font = _font(22)
    tb = d.textbbox((0, 0), label, font=font)
    lx, ly = (S - (tb[2] - tb[0])) / 2, S - 44
    d.text((lx + 1, ly + 1), label, font=font, fill=(245, 225, 160))
    d.text((lx, ly), label, font=font, fill=(70, 50, 20))
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
