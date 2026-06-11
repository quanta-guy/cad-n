"""Assemble the release folder (doc 15.3) from the PyInstaller one-folder build.

Run AFTER:  pyinstaller build\\cad_n.spec --noconfirm
Then:       python tools\\make_release.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cad_n import __version__  # noqa: E402

DIST_APP = ROOT / "dist" / "CAD-N"
DEST = ROOT / "release" / f"CAD-N_{__version__}"


def main() -> int:
    if not DIST_APP.exists():
        print(f"Build first: {DIST_APP} not found. Run pyinstaller build/cad_n.spec")
        return 1
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    # App (one-folder build) at the top of the version folder.
    shutil.copytree(DIST_APP, DEST, dirs_exist_ok=True)

    # Docs.
    for doc in ["USER_GUIDE.md", "CHANGELOG.md", "README.md"]:
        src = ROOT / doc
        if src.exists():
            shutil.copy2(src, DEST / doc)

    # Sample DXFs.
    samples = ROOT / "cad_n" / "resources" / "sample_dxf"
    if samples.exists():
        shutil.copytree(samples, DEST / "sample_dxf", dirs_exist_ok=True)

    # Licensing: CAD-N's MIT license, the NOTICE (LGPL statement for Qt/GEOS --
    # required to accompany binary distributions), the third-party inventory,
    # and the full third-party license texts.
    for doc in ["LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.md"]:
        shutil.copy2(ROOT / doc, DEST / doc)
    shutil.copytree(ROOT / "LICENSES", DEST / "LICENSES", dirs_exist_ok=True)

    total = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
    print(f"Release assembled at: {DEST}")
    print(f"  size: {total / 1e6:.1f} MB")
    print(f"  exe : {DEST / 'CAD-N.exe'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
