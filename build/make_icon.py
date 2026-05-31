#!/usr/bin/env python3
"""Generate the Whipper GUI application icon.

Produces ``build/python-appimage/whipper-gui.png`` — a flat-design optical
disc on a rounded dark tile. python-appimage bundles this PNG as the
AppImage's icon, and it's what shows in the KDE/GNOME app menu.

We commit the *generated* PNG (so the build needs no image tooling) and keep
this script as its source, so the icon can be regenerated or tweaked without
hand-editing a binary. Run it with Pillow installed:

    python3 -m pip install Pillow
    python3 build/make_icon.py

The drawing is done at 4x resolution and downscaled with LANCZOS, which is a
cheap way to get smooth, anti-aliased edges out of Pillow's polygon fills.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Final icon edge length in pixels, and the supersampling factor used while
# drawing (we render big, then shrink — instant anti-aliasing).
FINAL_SIZE: int = 512
SUPERSAMPLE: int = 4
SIZE: int = FINAL_SIZE * SUPERSAMPLE

OUTPUT_PATH: Path = Path(__file__).resolve().parent / "python-appimage" / "whipper-gui.png"

# Palette. Dark slate tile, a cyan→blue disc, a clear plastic hub.
TILE_TOP = (27, 42, 74)       # #1b2a4a
TILE_BOTTOM = (13, 27, 51)    # #0d1b33
DISC_TOP = (77, 208, 225)     # #4dd0e1 cyan
DISC_BOTTOM = (25, 118, 210)  # #1976d2 blue
HUB_COLOR = (214, 224, 237)   # light grey plastic hub


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """An RGBA image that fades top→bottom between two colours."""
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        # Linear interpolation factor down the image.
        t = y / (size - 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    return grad


def _circle_mask(size: int, cx: float, cy: float, radius: float) -> Image.Image:
    """A single-channel mask (L) with a filled white circle on black."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=255,
    )
    return mask


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # --- Rounded-square background tile -----------------------------------
    tile = _vertical_gradient(SIZE, TILE_TOP, TILE_BOTTOM)
    tile_mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.18), fill=255
    )
    img.paste(tile, (0, 0), tile_mask)

    cx = cy = SIZE / 2

    # --- The disc ----------------------------------------------------------
    disc_r = SIZE * 0.40
    disc_grad = _vertical_gradient(SIZE, DISC_TOP, DISC_BOTTOM)
    img.paste(disc_grad, (0, 0), _circle_mask(SIZE, cx, cy, disc_r))

    # Glossy highlight: a soft white sheen in the upper-left, clipped to the
    # disc so it reads as light glancing off the surface.
    sheen = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse(
        [cx - disc_r * 0.95, cy - disc_r * 1.15,
         cx + disc_r * 0.35, cy + disc_r * 0.10],
        fill=(255, 255, 255, 60),
    )
    # Keep the sheen inside the disc only.
    sheen.putalpha(Image.composite(
        sheen.getchannel("A"),
        Image.new("L", (SIZE, SIZE), 0),
        _circle_mask(SIZE, cx, cy, disc_r),
    ))
    img.alpha_composite(sheen)

    # --- Clear plastic hub + spindle hole ---------------------------------
    hub_r = SIZE * 0.165
    img.paste(
        Image.new("RGBA", (SIZE, SIZE), (*HUB_COLOR, 255)),
        (0, 0),
        _circle_mask(SIZE, cx, cy, hub_r),
    )
    # A thin inner ring groove (drawn as a slightly darker circle outline).
    ring = ImageDraw.Draw(img)
    ring.ellipse(
        [cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
        outline=(150, 165, 185, 255), width=int(SIZE * 0.006),
    )
    # The spindle hole: punch back to the tile gradient so it looks cut out.
    hole_r = SIZE * 0.058
    img.paste(tile, (0, 0), _circle_mask(SIZE, cx, cy, hole_r))

    # --- Downscale for anti-aliasing and save -----------------------------
    final = img.resize((FINAL_SIZE, FINAL_SIZE), Image.LANCZOS)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    final.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH} ({FINAL_SIZE}x{FINAL_SIZE})")


if __name__ == "__main__":
    main()
