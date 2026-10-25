"""Draws the extension's toolbar icons: two overlapping white rings (the website logo,
frontend/src/components/Logo.tsx) on a dark rounded square.

Run from the repo root:  pip install pillow && python3 scripts/make_icons.py
Writes extension/icons/icon16.png, icon32.png, icon48.png and icon128.png.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "extension" / "icons"
BG = (10, 10, 10, 255)          # #0a0a0a, same as the popup and card
RING = (245, 245, 245, 255)     # #f5f5f5, white like the site's text color
SCALE = 4                       # draw 4x bigger, then shrink: smooth edges even at 16px


def icon(size):
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(0.215 * big), fill=BG)
    r = 0.262 * big
    # same ring thickness as before at large sizes, but never thinner than 1.3px in the final icon,
    # so the rings don't fade away at 16px
    width = round(max(0.0586 * size, 1.3) * SCALE)
    for cx in (0.39 * big, 0.61 * big):   # the two centers are 0.84 radii apart, like the site logo (7 / 8.5)
        d.ellipse((cx - r, big / 2 - r, cx + r, big / 2 + r), outline=RING, width=width)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    for size in (16, 32, 48, 128):
        icon(size).save(OUT / f"icon{size}.png")
        print(f"wrote {OUT / f'icon{size}.png'}")
