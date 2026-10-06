"""Bandit Camp spinning wheel GIF generator.

Uses the ACTUAL Rust Bandit Camp wheel disc (extracted from Facepunch's
official artwork). Spins fast, eases out, stops, then stamps the exact
amount won in the hub. Plays once — no loop.
"""

from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

_ASSET = os.path.join(os.path.dirname(__file__), "wheel_disc.png")

SIZE = 220
BG = (14, 10, 16)
GOLD = (255, 215, 0)
POINTER_RED = (200, 45, 40)


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _load_disc() -> Image.Image:
    disc = Image.open(_ASSET).convert("RGB")
    return disc.resize((SIZE, SIZE), Image.LANCZOS)


def _draw_pointer(d: ImageDraw.Draw):
    # Small red triangle pointer at the top, like the real wheel's fixture.
    cx, top = SIZE // 2, 4
    d.polygon([(cx - 9, top), (cx + 9, top), (cx, top + 14)], fill=POINTER_RED,
              outline=(120, 20, 15))


def _draw_win_badge(img: Image.Image, amount: int) -> Image.Image:
    """Stamp the exact won amount in the hub on the stopped wheel."""
    d = ImageDraw.Draw(img)
    cx = cy = SIZE // 2
    text = f"+{amount}"
    font = _font(30)
    tb = d.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    pad_x, pad_y = 14, 8
    # Dark badge with gold border, centered in the hub.
    d.rounded_rectangle(
        [cx - tw / 2 - pad_x, cy - th / 2 - pad_y,
         cx + tw / 2 + pad_x, cy + th / 2 + pad_y],
        radius=12, fill=(20, 14, 10), outline=GOLD, width=3,
    )
    d.text((cx - tw / 2 - tb[0], cy - th / 2 - tb[1]), text,
           font=font, fill=GOLD)
    # "SCRAP" caption under the amount.
    cap_font = _font(11)
    cap = "SCRAP"
    ctb = d.textbbox((0, 0), cap, font=cap_font)
    d.text((cx - (ctb[2] - ctb[0]) / 2,
            cy + th / 2 + pad_y + 2),
           cap, font=cap_font, fill=(200, 180, 140))
    return img


def spin_wheel_gif(win_amount: int, frames: int = 26) -> io.BytesIO:
    """Render the spin. win_amount is the EXACT scrap won (e.g. 31).

    Plays once and stops with the amount stamped in the hub.
    """
    disc = _load_disc()

    # Random-ish but deterministic-feeling final angle: 3 full spins + offset.
    # The offset doesn't need to target a number — the badge shows the win.
    import random
    final_angle = random.uniform(0, 360)
    total_rot = 3 * 360 + final_angle

    out_frames: list[Image.Image] = []
    for f in range(frames):
        t = (f + 1) / frames
        eased = 1 - (1 - t) ** 3  # ease-out cubic
        angle = total_rot * eased
        # PIL rotates counterclockwise; negate for clockwise spin.
        rotated = disc.rotate(-angle, resample=Image.BICUBIC)
        frame = Image.new("RGB", (SIZE, SIZE), BG)
        frame.paste(rotated, (0, 0))
        d = ImageDraw.Draw(frame)
        _draw_pointer(d)
        out_frames.append(frame)

    # Hold on the stopped wheel, then stamp the win amount.
    stopped = out_frames[-1].copy()
    out_frames.append(stopped)  # one clean stopped frame
    for _ in range(8):
        out_frames.append(_draw_win_badge(stopped.copy(), win_amount))

    buf = io.BytesIO()
    # No loop extension -> plays exactly once and rests on the winner.
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=75)
    buf.seek(0)
    return buf


# Backwards-compat labels (unused by the new renderer, kept for the cog).
DAILY_LABELS = {"jackpot": "1000", "rare": "250", "uncommon": "100", "common": "50"}
VIP_LABELS = {"jackpot": "300", "rare": "100", "uncommon": "50", "common": "20"}
