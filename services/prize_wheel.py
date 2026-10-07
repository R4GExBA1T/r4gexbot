"""Hyper-realistic prize wheel spin animations for daily and VIP."""
import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))
SIZE = 280

# Segment values in clockwise order from the top pointer, matching the
# generated wheel images.
DAILY_SEGMENTS = [1000, 250, 100, 50, 25, 10]
VIP_SEGMENTS = [100, 300, 5, 10, 20, 50]


def _font(size: int) -> ImageFont.FreeTypeFont:
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    return ImageFont.load_default()


def _closest_segment(segments: list[int], amount: int) -> int:
    """Find the index of the segment closest to the winning amount."""
    return min(range(len(segments)), key=lambda i: abs(segments[i] - amount))


def _spin_wheel(image_name: str, segments: list[int], win_amount: int,
                frames: int = 26) -> io.BytesIO:
    """Spin the wheel, landing the winning segment at the top pointer.
    Stamps the exact winning amount in gold at the center hub."""
    wheel = Image.open(os.path.join(_ASSETS, image_name)).convert("RGB")
    W = wheel.width
    seg_deg = 360.0 / len(segments)

    # Winner segment index -> angle clockwise from top.
    win_idx = _closest_segment(segments, win_amount)
    win_angle = win_idx * seg_deg
    jitter = random.uniform(-seg_deg * 0.2, seg_deg * 0.2)
    # PIL rotate() is counter-clockwise positive.
    final_rot = win_angle + jitter
    total_deg = 4 * 360 + final_rot

    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        eased = 1 - (1 - t) ** 3
        angle = total_deg * eased
        rotated = wheel.rotate(angle, resample=Image.BICUBIC,
                               center=(W / 2, W / 2))
        small = rotated.resize((SIZE, SIZE), Image.LANCZOS)
        out_frames.append(small)

    # Final frame: stamp the exact amount in the hub.
    final = out_frames[-1].copy()
    d = ImageDraw.Draw(final)
    cx = cy = SIZE / 2
    font = _font(36)
    txt = f"+{win_amount}"
    tb = d.textbbox((0, 0), txt, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    # Gold pill behind the text.
    pad = 14
    d.rounded_rectangle(
        [cx - tw / 2 - pad, cy - th / 2 - pad,
         cx + tw / 2 + pad, cy + th / 2 + pad],
        radius=18, fill=(30, 20, 5, 230),
        outline=(255, 215, 0), width=3,
    )
    d.text((cx - tw / 2 - tb[0], cy - th / 2 - tb[1]),
           txt, font=font, fill=(255, 215, 0))
    out_frames[-1] = final
    out_frames.extend([final] * 14)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=70, loop=0)
    buf.seek(0)
    return buf


def spin_daily_gif(win_amount: int) -> io.BytesIO:
    """Spin the daily wheel, landing on the winning amount."""
    return _spin_wheel("wheel_daily.png", DAILY_SEGMENTS, win_amount)


def spin_vip_gif(win_amount: int) -> io.BytesIO:
    """Spin the prestigious VIP wheel, landing on the winning amount."""
    return _spin_wheel("wheel_vip.png", VIP_SEGMENTS, win_amount)
