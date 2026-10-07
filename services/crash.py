"""Hyper-realistic Crash game: multiplier climbs, cash out before it crashes."""
import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))
W, H = 480, 320


def _font(size: int) -> ImageFont.FreeTypeFont:
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    return ImageFont.load_default()


def roll_crash_point() -> float:
    """Standard crash distribution with ~1% house edge. Returns the multiplier
    at which the game crashes (minimum 1.00)."""
    r = random.random()
    if r < 0.01:
        return 1.00
    point = 0.99 / (1 - r)
    return round(min(point, 100.0), 2)


def crash_animation_gif(crash_point: float, cashout: float | None = None,
                        frames: int = 30) -> io.BytesIO:
    """Animate the multiplier climbing on the dramatic background.
    If cashout is given and crash_point >= cashout, the animation stops
    at the cashout (green). Otherwise it climbs to the crash (red)."""
    bg = Image.open(os.path.join(_ASSETS, "crash_bg.png")).convert("RGB")
    bg = bg.resize((W, H), Image.LANCZOS)

    # Determine the end of the animation.
    if cashout is not None and crash_point >= cashout:
        end_mult = cashout
        won = True
    else:
        end_mult = crash_point
        won = False

    # Chart area.
    pad_l, pad_r, pad_t, pad_b = 50, 30, 40, 50
    cw, ch = W - pad_l - pad_r, H - pad_t - pad_b

    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        # Ease-out for the climb, then hold.
        eased = 1 - (1 - t) ** 2
        mult = 1.0 + (end_mult - 1.0) * eased

        frame = bg.copy()
        d = ImageDraw.Draw(frame)

        # Draw the rising curve (exponential feel).
        pts = []
        n = 40
        for i in range(n + 1):
            ft = i / n * eased
            m = 1.0 + (end_mult - 1.0) * (1 - (1 - ft) ** 2)
            x = pad_l + (i / n) * cw * eased
            # Log-ish scale so early climb is visible.
            if end_mult > 1.01:
                y = pad_t + ch - (math.log(m) / math.log(end_mult)) * ch
            else:
                y = pad_t + ch
            pts.append((x, y))
        if len(pts) > 1:
            base = (80, 255, 140) if (won or t < 1.0) else (255, 70, 70)
            # Layered glow: wide faint, medium, then bright core.
            d.line(pts, fill=tuple(c // 4 for c in base), width=12)
            d.line(pts, fill=tuple(c // 2 for c in base), width=7)
            d.line(pts, fill=base, width=4)
            # Glow dot at the head with halo.
            hx, hy = pts[-1]
            d.ellipse([hx - 14, hy - 14, hx + 14, hy + 14],
                      fill=tuple(c // 4 for c in base))
            d.ellipse([hx - 8, hy - 8, hx + 8, hy + 8], fill=base)
            d.ellipse([hx - 3, hy - 3, hx + 3, hy + 3], fill=(255, 255, 255))

        # Multiplier text, big and centered, with dark outline for readability.
        font = _font(64)
        txt = f"{mult:.2f}x"
        tcolor = (80, 255, 140) if won else ((255, 70, 70) if t >= 1.0 else (255, 255, 255))
        tb = d.textbbox((0, 0), txt, font=font)
        tw = tb[2] - tb[0]
        tx, ty = W / 2 - tw / 2 - tb[0], 10
        # Outline.
        for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)]:
            d.text((tx + ox, ty + oy), txt, font=font, fill=(0, 0, 0))
        d.text((tx, ty), txt, font=font, fill=tcolor)

        # Target indicator.
        if cashout is not None and won:
            sfont = _font(20)
            stxt = f"TARGET {cashout:.2f}x"
            stb = d.textbbox((0, 0), stxt, font=sfont)
            stw = stb[2] - stb[0]
            d.text((W / 2 - stw / 2 - stb[0], 84), stxt, font=sfont,
                   fill=(80, 255, 140))

        out_frames.append(frame)

    # Hold the final frame.
    out_frames.extend([out_frames[-1]] * 14)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=80, loop=0)
    buf.seek(0)
    return buf
