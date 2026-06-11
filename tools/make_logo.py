"""Generate the neutral CAD-N project logo -> ``assets/logo.png``.

This is the public, vendor-neutral mark used for external/open-source builds.
It draws a sheet with a few true-shape parts nested inside it (the product in one
glance). ``tools/make_icon.py`` turns this PNG into the packaged ``icon.ico``.

Run:  python tools/make_logo.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "logo.png"
S = 1024  # render large; the icon builder downsamples with LANCZOS

# Palette
SLATE = (30, 41, 59, 255)        # sheet outline / dark
SHEET = (241, 245, 249, 255)     # sheet fill (light)
BLUE = (59, 130, 246, 255)
BLUE_D = (29, 78, 216, 255)
GREEN = (16, 185, 129, 255)
GREEN_D = (4, 120, 87, 255)
AMBER = (245, 158, 11, 255)
AMBER_D = (180, 83, 9, 255)


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # The sheet of stock.
    d.rounded_rectangle([(80, 80), (944, 944)], radius=88,
                        fill=SHEET, outline=SLATE, width=26)

    # Nested true-shape parts (the kerf gaps are the light sheet showing through).
    parts = [
        ([(170, 175), (470, 205), (440, 470), (160, 430)], BLUE, BLUE_D),    # blue quad, top-left
        ([(545, 180), (885, 215), (705, 470)], GREEN, GREEN_D),              # green triangle, top-right
        ([(165, 520), (445, 495), (500, 835), (185, 860)], AMBER, AMBER_D),  # amber quad, bottom-left
    ]
    for poly, fill, outline in parts:
        d.polygon(poly, fill=fill, outline=outline)

    # A round part, bottom-right.
    d.ellipse([(575, 545), (865, 835)], fill=GREEN, outline=GREEN_D, width=10)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
