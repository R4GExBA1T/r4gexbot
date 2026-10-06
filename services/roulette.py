"""Photorealistic roulette wheel spin that lands on the winning number."""
import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))
SIZE = 220
BALL_R = 7

# European roulette order, clockwise from 0 at the top.
EUROPEAN_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30,
    8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7,
    28, 12, 35, 3, 26,
]
POCKET_DEG = 360.0 / 37


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _build_numbered_wheel() -> Image.Image:
    """Overlay numbers 0-36 onto the blank wheel in European order."""
    wheel = Image.open(os.path.join(_ASSETS, "roulette_wheel_blank.png")).convert("RGB")
    W = wheel.width
    cx = cy = W / 2
    d = ImageDraw.Draw(wheel)
    # Number ring radius: pockets sit between the outer rim and the center cone.
    num_r = int(W * 0.335)
    font = _font(int(W * 0.038))

    for idx, num in enumerate(EUROPEAN_ORDER):
        # 0 at top (-90°), clockwise.
        ang = math.radians(-90 + idx * POCKET_DEG)
        nx = cx + num_r * math.cos(ang)
        ny = cy + num_r * math.sin(ang)
        txt = str(num)
        tb = d.textbbox((0, 0), txt, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        # Slight radial orientation for authenticity: rotate text to face outward.
        # PIL can't easily rotate text in place; draw upright (readable) instead.
        # Soft dark outline for legibility on red/black/green.
        x, y = nx - tw / 2 - tb[0], ny - th / 2 - tb[1]
        for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            d.text((x + ox, y + oy), txt, font=font, fill=(0, 0, 0))
        d.text((x, y), txt, font=font, fill=(255, 255, 255))
    return wheel


def roulette_spin_gif(winner: int, frames: int = 24) -> io.BytesIO:
    """Spin the wheel; it decelerates and the ball settles on `winner`
    at the top. Plays once."""
    wheel = _build_numbered_wheel()
    W = wheel.width

    # Winner's pocket angle (clockwise from top). Rotate the wheel so it
    # ends at the top: final rotation = -winner_angle (+ small jitter
    # inside the pocket so it doesn't look artificially perfect).
    winner_idx = EUROPEAN_ORDER.index(winner)
    winner_angle = winner_idx * POCKET_DEG
    jitter = random.uniform(-POCKET_DEG * 0.25, POCKET_DEG * 0.25)
    final_rot = -(winner_angle + jitter)
    total_deg = 3 * 360 + final_rot  # 3 full spins, then land

    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        eased = 1 - (1 - t) ** 3
        angle = total_deg * eased

        rotated = wheel.rotate(angle, resample=Image.BICUBIC, center=(W / 2, W / 2))
        small = rotated.resize((SIZE, SIZE), Image.LANCZOS)

        d = ImageDraw.Draw(small)
        cx = cy = SIZE / 2
        track_r = int(SIZE * 0.40)
        if t < 0.7:
            ball_angle = math.radians(-90 - (1 - t) * 720)
            br = track_r + 6
        else:
            st = (t - 0.7) / 0.3
            ball_angle = math.radians(-90 - (1 - st) * 120)
            br = track_r + 6 - int(st * 6)
        bx = cx + br * math.cos(ball_angle)
        by = cy + br * math.sin(ball_angle)
        d.ellipse([bx - BALL_R - 1, by - BALL_R + 1, bx + BALL_R - 1, by + BALL_R + 1],
                  fill=(0, 0, 0, 160))
        d.ellipse([bx - BALL_R, by - BALL_R, bx + BALL_R, by + BALL_R],
                  fill=(235, 235, 240))
        d.ellipse([bx - BALL_R + 2, by - BALL_R + 1, bx - 1, by - 2],
                  fill=(255, 255, 255))
        out_frames.append(small)

    out_frames.extend([out_frames[-1]] * 12)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=70, loop=0)
    buf.seek(0)
    return buf
