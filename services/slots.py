"""Photorealistic slot machine spin animation with Rust-themed symbols."""
import io
import os
import random

from PIL import Image

_ASSETS = os.path.dirname(os.path.abspath(__file__))

# Symbol key -> (filename, display name)
SYMBOLS = {
    "seven": ("slot_seven.png", "7️⃣"),
    "supplydrop": ("slot_supplydrop.png", "📦"),
    "ak": ("slot_ak.png", "🔫"),
    "facemask": ("slot_facemask.png", "🎭"),
    "sulfur": ("slot_sulfur.png", "🟡"),
    "scrap": ("slot_scrap.png", "⚙️"),
}
SYMBOL_KEYS = list(SYMBOLS.keys())

# Window positions on the slot machine base (fractions of image size).
# Tightly fitted to the three dark windows.
WINDOWS = [
    (0.258, 0.337, 0.358, 0.600),  # left window
    (0.383, 0.337, 0.483, 0.600),  # middle window
    (0.508, 0.337, 0.608, 0.600),  # right window
]


def _load(name: str) -> Image.Image:
    return Image.open(os.path.join(_ASSETS, name)).convert("RGB")


def slots_spin_gif(result: list[str], frames: int = 18) -> io.BytesIO:
    """Animate the slot reels spinning, landing on `result` (3 symbol keys).
    Plays once."""
    machine = _load("slot_machine.png")
    W, H = machine.size
    symbols = {k: _load(SYMBOLS[k][0]) for k in SYMBOL_KEYS}

    # Precompute window rects in pixels.
    rects = [
        (int(x1 * W), int(y1 * H), int(x2 * W), int(y2 * H))
        for x1, y1, x2, y2 in WINDOWS
    ]

    # Crop to the reel area for a tighter, more readable framing.
    crop_x1 = int(0.20 * W)
    crop_x2 = int(0.68 * W)
    crop_y1 = int(0.25 * H)
    crop_y2 = int(0.68 * H)

    out_frames: list[Image.Image] = []
    # Each reel stops at a different time (left to right).
    stop_frames = [frames - 8, frames - 4, frames]
    for f in range(frames):
        frame = machine.copy()
        for i, (x1, y1, x2, y2) in enumerate(rects):
            ww, hh = x2 - x1, y2 - y1
            if f < stop_frames[i]:
                key = random.choice(SYMBOL_KEYS)
            else:
                key = result[i]
            sym = symbols[key].resize((ww, hh), Image.LANCZOS)
            frame.paste(sym, (x1, y1))
        # Crop to reels, then scale for Discord.
        cropped = frame.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        small = cropped.resize((360, int(360 * cropped.height / cropped.width)),
                               Image.LANCZOS)
        out_frames.append(small)

    # Hold the final frame.
    out_frames.extend([out_frames[-1]] * 10)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True,
                       append_images=out_frames[1:], duration=80, loop=0)
    buf.seek(0)
    return buf
