"""Generate the application icon as a multi-size .ico.

Source image, by build flavour:
  * Public / external (default): the neutral project mark ``assets/logo.png``
    (regenerate it with ``python tools/make_logo.py``).
  * Internal: set ``CADN_INTERNAL=1`` to bake the company logo from
    ``branding/company_logo.png`` instead (that file is git-ignored).

The icon feeds both the packaged .exe (PyInstaller ``icon=``) and the running
app's window/taskbar icon (``main._icon_path``), so regenerating here updates
everywhere.

Run:  python tools/make_icon.py                              (public icon)
      set CADN_INTERNAL=1 & python tools/make_icon.py    (company icon, Windows)
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_LOGO = ROOT / "assets" / "logo.png"
INTERNAL_LOGO = ROOT / "branding" / "company_logo.png"
OUT = ROOT / "cad_n" / "resources" / "icon.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def _source() -> Path:
    """Pick the logo to bake into the icon (see module docstring)."""
    if os.environ.get("CADN_INTERNAL") == "1" and INTERNAL_LOGO.exists():
        return INTERNAL_LOGO
    return PUBLIC_LOGO


def _square(img: Image.Image, size: int) -> Image.Image:
    """Return a centred, square ``size`` x ``size`` RGBA copy of *img*.

    Non-square logos are padded with transparency so nothing is cropped or
    stretched; the result is then high-quality downscaled.
    """
    img = img.convert("RGBA")
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    src = _source()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = _square(Image.open(src), 256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT} from {src}")


if __name__ == "__main__":
    main()
