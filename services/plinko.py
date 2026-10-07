"""Hyper-realistic Plinko: chrome ball bounces down the pegs."""
import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.dirname(os.path.abspath(__file__))

ROWS = 12  # peg rows
W, H = 400, 560

# Multiplier tables per risk level (13 bins for 12 rows).
MULTIPLIERS = {
    "low":    [10, 3, 1.6, 1.4, 1.1, 1, 0.5, 1, 1.1, 1.4, 1.6, 3, 10],
    "medium": [30, 6, 2, 1.5, 1.1, 1, 0.5, 1, 1.1, 1.5, 2, 6, 30],
    "high":   [100, 20, 5, 2, 1.2, 1, 0.3, 1, 1.2, 2, 5, 20, 100],
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    bundled = os.path.join(_ASSETS, "DejaVuSans-Bold.ttf")
    if os.path.exists(bundled):
        return ImageFont.truetype(bundled, size)
    return ImageFont.load_default()


def _load_ball(size: int) -> Image.Image | None:
    path = os.path.join(_ASSETS, "plinko_ball.png")
    if os.path.exists(path):
        b = Image.open(path).convert("RGBA")
        return b.resize((size, size), Image.LANCZOS)
    return None


def simulate_drop() -> tuple[list[tuple[float, float]], int]:
    """Simulate the ball path. Returns (path points, final bin index)."""
    # Peg layout: row r has r+1 pegs, centered.
    top_y = 70
    row_gap = 32
    col_gap = 30
    cx = W / 2

    # Ball starts at top center.
    x = cx
    y = top_y - 20
    path = [(x, y)]

    bin_idx = 0  # tracks right-moves
    for r in range(ROWS):
        # Pegs in this row: positions cx + (i - r/2) * col_gap for i in 0..r
        # Ball hits the nearest peg and bounces left or right.
        y_peg = top_y + r * row_gap
        # Find nearest peg x.
        # Pegs: cx - r*col_gap/2 + i*col_gap
        rel = (x - (cx - r * col_gap / 2)) / col_gap
        nearest = round(rel)
        nearest = max(0, min(r, nearest))
        peg_x = cx - r * col_gap / 2 + nearest * col_gap

        # Bounce: 50/50 left or right.
        go_right = random.random() < 0.5
        if go_right:
            bin_idx += 1
            x = peg_x + col_gap / 2
        else:
            x = peg_x - col_gap / 2
        y = y_peg + row_gap * 0.7
        path.append((peg_x, y_peg))  # touch the peg
        path.append((x, y))

    return path, bin_idx


def plinko_animation_gif(risk: str, balls: int = 1,
                         frames: int = 36) -> tuple[io.BytesIO, list[float]]:
    """Animate chrome ball(s) dropping. Returns (gif, [multipliers]).
    Balls drop with a slight stagger for visual appeal."""
    mults = MULTIPLIERS[risk]

    # Simulate each ball's path.
    all_paths: list[tuple[list[tuple[float, float]], int]] = []
    for _ in range(balls):
        path, bin_idx = simulate_drop()
        all_paths.append((path, bin_idx))
    multipliers = [mults[bin_idx] for _, bin_idx in all_paths]

    bg = Image.open(os.path.join(_ASSETS, "plinko_bg.png")).convert("RGB")
    bg = bg.resize((W, H), Image.LANCZOS)

    # Peg positions.
    top_y = 70
    row_gap = 32
    col_gap = 30
    cx = W / 2
    pegs = []
    for r in range(ROWS):
        for i in range(r + 1):
            px = cx - r * col_gap / 2 + i * col_gap
            py = top_y + r * row_gap
            pegs.append((px, py))

    # Bin slots at the bottom.
    bin_y = top_y + ROWS * row_gap + 10
    bin_w = col_gap
    bin_top = bin_y
    bin_bot = bin_y + 44

    ball_size = 20
    ball_img = _load_ball(ball_size)

    # Stagger: each ball starts a few frames after the previous.
    stagger = 8
    total_frames = frames + stagger * (balls - 1)
    win_bins = {bin_idx for _, bin_idx in all_paths}

    out_frames: list[Image.Image] = []
    for f in range(total_frames):
        frame = bg.copy()
        d = ImageDraw.Draw(frame)

        # Draw pegs.
        for px, py in pegs:
            d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(120, 120, 130))
            d.ellipse([px - 2, py - 3, px + 1, py], fill=(220, 220, 230))

        # Draw bins.
        font = _font(11)
        for b in range(ROWS + 1):
            bcx = cx - ROWS * col_gap / 2 + b * col_gap
            x0b, x1b = bcx - bin_w / 2 + 2, bcx + bin_w / 2 - 2
            m = mults[b]
            if m < 1:
                col = (180, 60, 60)
            elif m < 2:
                col = (180, 160, 60)
            else:
                col = (60, 180, 80)
            # Highlight winning bins near the end.
            if f >= total_frames - 8 and b in win_bins:
                d.rounded_rectangle([x0b - 2, bin_top - 2, x1b + 2, bin_bot + 2],
                                    radius=6, outline=(255, 215, 0), width=3)
            d.rounded_rectangle([x0b, bin_top, x1b, bin_bot],
                                radius=6, fill=col)
            txt = f"{m}x" if m != int(m) else f"{int(m)}x"
            tb = d.textbbox((0, 0), txt, font=font)
            tw = tb[2] - tb[0]
            d.text((bcx - tw / 2 - tb[0], bin_top + 12 - tb[1]),
                   txt, font=font, fill=(255, 255, 255))

        # Draw each ball at its staggered position.
        for bi, (path, _) in enumerate(all_paths):
            start = bi * stagger
            local_f = f - start
            if local_f < 0:
                continue  # not dropped yet
            local_f = min(local_f, frames - 1)
            t = (local_f + 1) / frames
            eased = t ** 0.9
            total_segs = len(path) - 1
            pos = eased * total_segs
            i0 = int(pos)
            i1 = min(i0 + 1, total_segs)
            ft = pos - i0
            x0, y0 = path[i0]
            x1, y1 = path[i1]
            bx = x0 + (x1 - x0) * ft
            by = y0 + (y1 - y0) * ft
            if ball_img:
                frame.paste(ball_img,
                            (int(bx - ball_size / 2), int(by - ball_size / 2)),
                            ball_img)
            else:
                d.ellipse([bx - 9, by - 9, bx + 9, by + 9],
                          fill=(200, 200, 210))

        out_frames.append(frame)

    # Hold final frame.
    out_frames.extend([out_frames[-1]] * 16)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=60, loop=0)
    buf.seek(0)
    return buf, multipliers
