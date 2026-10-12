"""Player stat card renderer — dark royal purple Rust theme."""
from __future__ import annotations

import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 800, 440
BG = (16, 8, 32)
PANEL = (28, 14, 52)
PURPLE = (139, 0, 255)
PURPLE_DIM = (90, 40, 160)
GOLD = (255, 215, 0)
WHITE = (240, 235, 250)
GRAY = (150, 140, 170)
GREEN = (80, 220, 120)
RED = (235, 90, 90)

FONT_PATH = os.path.join(os.path.dirname(__file__), "DejaVuSans-Bold.ttf")


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _fmt_playtime(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h >= 24:
        return f"{h // 24}d {h % 24}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def render(gamertag: str, kills: int, deaths: int, best_streak: int,
           scrap_earned: int, playtime_seconds: int,
           protection_text: str = "") -> str:
    """Render a stat card PNG. Returns the file path."""
    kd = (kills / deaths) if deaths else float(kills)
    kd_str = f"{kd:.2f}"

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Border frame
    d.rectangle([4, 4, W - 5, H - 5], outline=PURPLE_DIM, width=3)
    d.rectangle([12, 12, W - 13, H - 13], outline=(50, 25, 90), width=1)

    # Header bar
    d.rectangle([16, 16, W - 17, 92], fill=PANEL)
    d.text((36, 28), "R4GE 3X  //  COMBAT RECORD",
           font=_font(22), fill=PURPLE)
    # Gamertag (truncate if absurdly long)
    name = gamertag if len(gamertag) <= 24 else gamertag[:23] + "…"
    d.text((36, 54), name, font=_font(30), fill=WHITE)

    # K/D hero number, right side of header
    d.text((W - 200, 30), "K/D", font=_font(22), fill=GRAY)
    d.text((W - 200, 54), kd_str, font=_font(30),
           fill=GREEN if kd >= 1 else RED)

    # Stat tiles
    tiles = [
        ("KILLS", str(kills), WHITE),
        ("DEATHS", str(deaths), WHITE),
        ("BEST STREAK", str(best_streak), GOLD),
        ("SCRAP EARNED", f"+{scrap_earned}", GOLD),
        ("PLAYTIME", _fmt_playtime(playtime_seconds), WHITE),
    ]
    tx, ty = 36, 130
    tw, th, gap = 220, 120, 24
    for i, (label, value, color) in enumerate(tiles):
        x = tx + (i % 3) * (tw + gap)
        y = ty + (i // 3) * (th + gap)
        d.rectangle([x, y, x + tw, y + th], fill=PANEL,
                    outline=PURPLE_DIM, width=2)
        d.text((x + 18, y + 14), label, font=_font(20), fill=GRAY)
        d.text((x + 18, y + 48), value, font=_font(34), fill=color)

    # Footer: protection status
    fy = ty + 2 * (th + gap) + 16
    d.rectangle([16, fy, W - 17, fy + 64], fill=PANEL)
    prot = protection_text or "⚔️ No protection"
    d.text((36, fy + 18), prot, font=_font(24), fill=WHITE)

    fd, path = tempfile.mkstemp(suffix=".png", prefix="statcard_")
    os.close(fd)
    img.save(path)
    return path
