"""Killfeed card renderer — dark royal purple Rust theme.

Bakes the killer's name in PURPLE and the victim's in RED as real image
text, so the colours show on every Discord client (ANSI text colour in
embeds doesn't render everywhere).
"""
from __future__ import annotations

import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

W = 1000
BG = (16, 8, 32)
PANEL = (28, 14, 52)
FRAME_DIM = (50, 25, 90)
PURPLE = (139, 0, 255)
KILLER_PURPLE = (178, 102, 255)
VICTIM_RED = (255, 77, 77)
GOLD = (255, 215, 0)
WHITE = (240, 235, 250)
GRAY = (150, 140, 170)
ORANGE = (255, 140, 0)
RED = (255, 60, 60)

FONT_PATH = os.path.join(os.path.dirname(__file__), "DejaVuSans-Bold.ttf")


def _font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _fit_name_font(d: ImageDraw.ImageDraw, killer: str, victim: str,
                   max_width: int) -> int:
    """Largest font size (<=46) where 'killer » victim' fits max_width."""
    size = 46
    while size > 24:
        f = _font(size)
        w = (d.textlength(killer, font=f) + d.textlength("  »  ", font=f)
             + d.textlength(victim, font=f))
        if w <= max_width:
            return size
        size -= 2
    return size


def _draw_segments(d: ImageDraw.ImageDraw, x: int, y: int,
                   segments: list[tuple[str, tuple]], font) -> int:
    """Draw (text, colour) runs left to right. Returns the end x."""
    for text, color in segments:
        d.text((x, y), text, font=font, fill=color)
        x += d.textlength(text, font=font)
    return x


def render(killer: str, victim: str, kills: int, deaths: int, streak: int,
           victim_streak: int, awarded: int) -> str:
    """Render a killfeed card PNG. Returns the temp file path."""
    kd = (kills / deaths) if deaths else float(kills)

    # Border colour escalates with the killer's streak
    if streak >= 10:
        frame = RED
    elif streak >= 5:
        frame = ORANGE
    else:
        frame = PURPLE

    callout = None
    if streak >= 10:
        callout = ("UNSTOPPABLE — DOUBLE-DIGIT STREAK!", RED)
    elif streak >= 7:
        callout = ("ON A TEAR — 7-KILL STREAK!", ORANGE)
    elif streak >= 5:
        callout = ("RAMPAGE — 5-KILL STREAK!", ORANGE)
    elif streak >= 3:
        callout = ("HEATING UP — 3-KILL STREAK", ORANGE)

    # Height grows with the optional lines
    extra = (1 if callout else 0) + (1 if victim_streak >= 3 else 0)
    H = 252 + 58 * extra

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, W - 5, H - 5], outline=frame, width=4)
    d.rectangle([13, 13, W - 14, H - 14], outline=FRAME_DIM, width=1)

    # Header
    d.rectangle([17, 17, W - 18, 76], fill=PANEL)
    d.text((36, 32), "R4GE 3X  //  KILLFEED", font=_font(24), fill=PURPLE)
    kill_no = f"KILL #{kills}"
    d.text((W - 36 - d.textlength(kill_no, font=_font(24)), 32),
           kill_no, font=_font(24), fill=GRAY)

    # Names: killer PURPLE » victim RED
    kname = killer if len(killer) <= 24 else killer[:23] + "…"
    vname = victim if len(victim) <= 24 else victim[:23] + "…"
    size = _fit_name_font(d, kname, vname, W - 72)
    nf = _font(size)
    total = (d.textlength(kname, font=nf) + d.textlength("  »  ", font=nf)
             + d.textlength(vname, font=nf))
    x = (W - total) / 2
    _draw_segments(d, x, 100,
                   [(kname, KILLER_PURPLE), ("  »  ", WHITE),
                    (vname, VICTIM_RED)], nf)

    y = 168
    if callout:
        text, color = callout
        cf = _font(30)
        d.text(((W - d.textlength(text, font=cf)) / 2, y), text,
               font=cf, fill=color)
        y += 58
    if victim_streak >= 3:
        ef = _font(26)
        segs = [(kname, KILLER_PURPLE), (" ended ", WHITE),
                (vname, VICTIM_RED),
                (f"'s {victim_streak}-kill streak!", WHITE)]
        total = sum(d.textlength(t, font=ef) for t, _ in segs)
        _draw_segments(d, (W - total) / 2, y + 4, segs, ef)
        y += 58

    # Stats line
    sf = _font(28)
    segs = [(f"{kills}K / {deaths}D", WHITE),
            ("   •   ", GRAY),
            (f"{kd:.2f} K/D", WHITE)]
    if streak >= 2:
        segs += [("   •   ", GRAY), (f"STREAK {streak}", GOLD)]
    if awarded > 0:
        segs += [("   •   ", GRAY), (f"+{awarded} SCRAP", GOLD)]
    total = sum(d.textlength(t, font=sf) for t, _ in segs)
    _draw_segments(d, (W - total) / 2, y + 6, segs, sf)

    fd, path = tempfile.mkstemp(suffix=".png", prefix="killcard_")
    os.close(fd)
    img.save(path)
    return path
