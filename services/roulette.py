"""Photorealistic roulette wheel spin that lands on the winning number."""
import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))
SIZE = 320  # output GIF size (larger for readable numbers)
BALL_R = 9

# European roulette order, clockwise from 0 at the top.
EUROPEAN_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30,
    8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7,
    28, 12, 35, 3, 26,
]
POCKET_DEG = 360.0 / 37


def _font(size: int) -> ImageFont.FreeTypeFont:
    # Bundled font first (Railway may not have system fonts).
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _build_numbered_wheel() -> Image.Image:
    """Overlay numbers 0-36 onto the perfect 37-pocket wheel in European order,
    each rotated to follow the wheel like a real casino table."""
    wheel = Image.open(os.path.join(_ASSETS, "roulette_wheel_perfect.png")).convert("RGBA")
    W = wheel.width
    cx = cy = W / 2
    num_r = int(W * 0.290)  # center of the wider pocket ring
    font = _font(int(W * 0.030))  # smaller, refined

    for idx, num in enumerate(EUROPEAN_ORDER):
        # 0 at top (-90°), clockwise. deg_cw = clockwise degrees from top.
        deg_cw = idx * POCKET_DEG
        ang = math.radians(-90 + deg_cw)
        nx = cx + num_r * math.cos(ang)
        ny = cy + num_r * math.sin(ang)
        txt = str(num)

        # Render the number on its own tile, then rotate so its "up"
        # points outward from the center (readable from outside the wheel).
        tb = font.getbbox(txt)
        tw, th = tb[2] - tb[0] + 8, tb[3] - tb[1] + 8
        tile = Image.new("RGBA", (tw * 2, th * 2), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        tx, ty = tw / 2 - tb[0], th / 2 - tb[1]
        # Clean thin outline for crisp legibility.
        for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            td.text((tx + ox, ty + oy), txt, font=font, fill=(0, 0, 0, 255))
        td.text((tx, ty), txt, font=font, fill=(255, 255, 255, 255))
        # Rotate: at top (deg_cw=0) the number is upright; rotate clockwise
        # as we move around so the top of the digit points outward.
        rotated = tile.rotate(-deg_cw, resample=Image.BICUBIC, expand=True)
        wheel.alpha_composite(
            rotated, (int(nx - rotated.width / 2), int(ny - rotated.height / 2))
        )
    return wheel.convert("RGB")


def roulette_spin_gif(winner: int, frames: int = 24) -> io.BytesIO:
    """Spin the wheel; it decelerates and the ball settles on `winner`
    at the top. Plays once."""
    wheel = _build_numbered_wheel()
    W = wheel.width

    # Winner's pocket angle (clockwise from top). PIL rotate() is
    # counter-clockwise-positive: rotate(winner_angle) moves the winner
    # to the top. Add small jitter so it doesn't look artificially perfect.
    winner_idx = EUROPEAN_ORDER.index(winner)
    winner_angle = winner_idx * POCKET_DEG
    jitter = random.uniform(-POCKET_DEG * 0.25, POCKET_DEG * 0.25)
    final_rot = winner_angle + jitter
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
