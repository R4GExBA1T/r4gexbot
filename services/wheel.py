"""Bandit Camp spinning wheel GIF generator.

Modeled on Rust's actual Bandit Camp wheel: many thin numbered segments,
a big cream hub, rusty rim, and a small red pointer. Spins fast, eases
out, and STOPS on the winning tier (plays once, no loop).
"""

from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw, ImageFont

SIZE = 260
CENTER = SIZE // 2
WHEEL_R = 112
HUB_R = 42
BG = (14, 10, 16)
CREAM = (232, 222, 200)
RUST = (122, 72, 40)
POINTER_RED = (200, 40, 40)

# 20 thin segments like the real wheel. (tier, label, color)
# Distribution roughly mirrors the odds: 1 jackpot / 2 rare / 5 uncommon / 12 common.
def _segments(labels: dict[str, str]) -> list[tuple[str, str, tuple[int, int, int]]]:
    common_colors = [(214, 186, 60), (86, 160, 90)]  # yellow, green alternating
    segs: list[tuple[str, str, tuple[int, int, int]]] = []
    segs.append(("jackpot", labels["jackpot"], (200, 90, 50)))      # red-orange
    segs.append(("common", labels["common"], common_colors[0]))
    segs.append(("rare", labels["rare"], (150, 110, 190)))          # purple
    segs.append(("common", labels["common"], common_colors[1]))
    segs.append(("uncommon", labels["uncommon"], (80, 140, 200)))   # blue
    segs.append(("common", labels["common"], common_colors[0]))
    segs.append(("common", labels["common"], common_colors[1]))
    segs.append(("rare", labels["rare"], (150, 110, 190)))
    segs.append(("common", labels["common"], common_colors[0]))
    segs.append(("uncommon", labels["uncommon"], (80, 140, 200)))
    segs.append(("common", labels["common"], common_colors[1]))
    segs.append(("common", labels["common"], common_colors[0]))
    segs.append(("uncommon", labels["uncommon"], (80, 140, 200)))
    segs.append(("common", labels["common"], common_colors[1]))
    segs.append(("common", labels["common"], common_colors[0]))
    segs.append(("uncommon", labels["uncommon"], (80, 140, 200)))
    segs.append(("common", labels["common"], common_colors[1]))
    segs.append(("common", labels["common"], common_colors[0]))
    segs.append(("uncommon", labels["uncommon"], (80, 140, 200)))
    segs.append(("common", labels["common"], common_colors[1]))
    return segs


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_wheel(base: Image.Image, rotation_deg: float,
                segs: list[tuple[str, str, tuple[int, int, int]]]) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img)
    bbox = [CENTER - WHEEL_R, CENTER - WHEEL_R, CENTER + WHEEL_R, CENTER + WHEEL_R]

    n = len(segs)
    seg_angle = 360 / n
    font = _font(13)

    for i, (_tier, label, color) in enumerate(segs):
        start = i * seg_angle + rotation_deg
        d.pieslice(bbox, start=start, end=start + seg_angle, fill=color,
                   outline=(30, 22, 18), width=2)
        # Number near the outer edge, rotated radially like the real wheel.
        mid = math.radians(start + seg_angle / 2)
        lx = CENTER + math.cos(mid) * (WHEEL_R * 0.80)
        ly = CENTER + math.sin(mid) * (WHEEL_R * 0.80)
        tb = d.textbbox((0, 0), label, font=font)
        d.text((lx - (tb[2] - tb[0]) / 2, ly - (tb[3] - tb[1]) / 2),
               label, font=font, fill=(25, 20, 15))

    # Rusty rim.
    d.ellipse(bbox, outline=RUST, width=7)
    # Big cream hub like the real wheel.
    d.ellipse([CENTER - HUB_R, CENTER - HUB_R, CENTER + HUB_R, CENTER + HUB_R],
              fill=CREAM, outline=(60, 45, 30), width=3)
    # Hub spokes (rusty cross, like the reference).
    d.line([CENTER - HUB_R + 4, CENTER, CENTER + HUB_R - 4, CENTER],
           fill=(110, 80, 55), width=5)
    d.line([CENTER, CENTER - HUB_R + 4, CENTER, CENTER + HUB_R - 4],
           fill=(110, 80, 55), width=5)
    d.ellipse([CENTER - 10, CENTER - 10, CENTER + 10, CENTER + 10],
              fill=(70, 50, 35), outline=CREAM, width=2)

    # Small red pointer at the top.
    px, py = CENTER, CENTER - WHEEL_R - 10
    d.polygon([(px - 8, py - 12), (px + 8, py - 12), (px, py + 2)], fill=POINTER_RED)
    return img


def spin_wheel_gif(tier: str, labels: dict[str, str], frames: int = 24) -> io.BytesIO:
    """Render the spin. Plays ONCE and stops on the winning tier (no loop).

    tier: winning tier ("jackpot" | "rare" | "uncommon" | "common").
    labels: tier -> number shown on segments.
    """
    segs = _segments(labels)
    n = len(segs)
    seg_angle = 360 / n

    # Rotation that puts a winning segment's center at the top (270° in PIL).
    win_idx = next(i for i, (t, _, _) in enumerate(segs) if t == tier)
    target_rot = (270 - (win_idx * seg_angle + seg_angle / 2)) % 360

    total_rot = 3 * 360 + target_rot  # 3 full spins, then land

    base = Image.new("RGB", (SIZE, SIZE), BG)
    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        eased = 1 - (1 - t) ** 3
        out_frames.append(_draw_wheel(base, total_rot * eased, segs))

    # Hold the winning frame so it clearly STOPS there. No loop extension =
    # the GIF plays exactly once and rests on the winner.
    out_frames.extend([out_frames[-1]] * 10)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=80)
    buf.seek(0)
    return buf


DAILY_LABELS = {"jackpot": "1000", "rare": "250", "uncommon": "100", "common": "50"}
VIP_LABELS = {"jackpot": "300", "rare": "100", "uncommon": "50", "common": "20"}
