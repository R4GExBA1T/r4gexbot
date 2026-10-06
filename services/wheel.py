"""Bandit Camp spinning wheel GIF generator.

Renders a proper segmented gambling wheel (like Rust's Bandit Camp) as an
animated GIF: it spins fast, eases out, and lands the pointer on the
winning tier's segment.
"""

from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw, ImageFont

SIZE = 420
CENTER = SIZE // 2
WHEEL_R = 175
HUB_R = 34
BG = (18, 12, 24)          # dark royal purple-black
RIM = (60, 40, 90)
POINTER = (255, 215, 0)    # gold pointer

# tier -> (label, segment color)
TIER_STYLE = {
    "jackpot": ("{top}", (212, 175, 55)),    # gold
    "rare": ("{top}", (155, 89, 182)),       # purple
    "uncommon": ("{top}", (52, 152, 219)),   # blue
    "common": ("{top}", (120, 120, 130)),    # grey
}

SEGMENT_ORDER = ["jackpot", "common", "rare", "common",
                 "uncommon", "common", "rare", "common"]


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_wheel(base: Image.Image, rotation_deg: float, labels: dict[str, str]) -> Image.Image:
    """Draw one frame of the wheel rotated by rotation_deg (clockwise)."""
    img = base.copy()
    d = ImageDraw.Draw(img)
    bbox = [CENTER - WHEEL_R, CENTER - WHEEL_R, CENTER + WHEEL_R, CENTER + WHEEL_R]

    n = len(SEGMENT_ORDER)
    seg_angle = 360 / n
    font = _font(26)

    for i, tier in enumerate(SEGMENT_ORDER):
        label_tpl, color = TIER_STYLE[tier]
        label = label_tpl.format(top=labels[tier])
        # PIL pieslice: 0° at 3 o'clock, increasing clockwise.
        start = i * seg_angle + rotation_deg
        d.pieslice(bbox, start=start, end=start + seg_angle, fill=color,
                   outline=(20, 20, 30), width=3)
        # Label in the middle of the segment.
        mid = math.radians(start + seg_angle / 2)
        lx = CENTER + math.cos(mid) * (WHEEL_R * 0.62)
        ly = CENTER + math.sin(mid) * (WHEEL_R * 0.62)
        # Keep text upright-ish: draw centered.
        tb = d.textbbox((0, 0), label, font=font)
        d.text((lx - (tb[2] - tb[0]) / 2, ly - (tb[3] - tb[1]) / 2),
               label, font=font, fill=(15, 15, 20))

    # Rim + hub.
    d.ellipse(bbox, outline=RIM, width=10)
    d.ellipse([CENTER - HUB_R, CENTER - HUB_R, CENTER + HUB_R, CENTER + HUB_R],
              fill=(40, 26, 60), outline=POINTER, width=4)
    hub_font = _font(20)
    tb = d.textbbox((0, 0), "R4GE", font=hub_font)
    d.text((CENTER - (tb[2] - tb[0]) / 2, CENTER - (tb[3] - tb[1]) / 2),
           "R4GE", font=hub_font, fill=POINTER)

    # Pointer at the top.
    px, py = CENTER, CENTER - WHEEL_R - 18
    d.polygon([(px - 16, py - 22), (px + 16, py - 22), (px, py + 6)], fill=POINTER)
    return img


def _base_frame(title: str) -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE + 40), BG)
    d = ImageDraw.Draw(img)
    font = _font(24)
    tb = d.textbbox((0, 0), title, font=font)
    d.text(((SIZE - (tb[2] - tb[0])) / 2, 8), title, font=font, fill=(200, 180, 220))
    return img


def spin_wheel_gif(tier: str, labels: dict[str, str], title: str = "BANDIT CAMP",
                   frames: int = 28) -> io.BytesIO:
    """Render the spin animation. Returns a BytesIO with the GIF data.

    tier: the winning tier ("jackpot" | "rare" | "uncommon" | "common").
    labels: tier -> payout label shown on segments, e.g. {"jackpot": "1000", ...}.
    """
    n = len(SEGMENT_ORDER)
    seg_angle = 360 / n

    # Find a winning segment index, then the rotation that puts its center at the top.
    # Top of the wheel in PIL coords is 270°.
    win_idx = next(i for i, t in enumerate(SEGMENT_ORDER) if t == tier)
    target_rot = (270 - (win_idx * seg_angle + seg_angle / 2)) % 360

    full_spins = 4
    total_rot = full_spins * 360 + target_rot

    base = _base_frame(title)
    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        eased = 1 - (1 - t) ** 3  # ease-out cubic
        rot = total_rot * eased
        out_frames.append(_draw_wheel(base, rot, labels))

    # Hold the final frame a beat longer.
    out_frames.extend([out_frames[-1]] * 6)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=70, loop=0)
    buf.seek(0)
    return buf


DAILY_LABELS = {"jackpot": "1000", "rare": "250", "uncommon": "100", "common": "10-50"}
VIP_LABELS = {"jackpot": "300", "rare": "100", "uncommon": "50", "common": "5-20"}
