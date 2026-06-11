"""Persist the programmatic DXF fixtures to disk.

Writes every builder in tests/dxfgen.py to:
  * tests/fixtures/        (used by golden/visual tooling)
  * cad_n/resources/sample_dxf/  (shipped in the release bundle)

Run:  python tools/make_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import dxfgen  # noqa: E402

OUT_DIRS = [ROOT / "tests" / "fixtures", ROOT / "cad_n" / "resources" / "sample_dxf"]


def main() -> None:
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    for name, builder in dxfgen.ALL_BUILDERS.items():
        doc = builder()
        for d in OUT_DIRS:
            path = d / f"{name}.dxf"
            doc.saveas(path)
        print(f"wrote {name}.dxf")
    print(f"\n{len(dxfgen.ALL_BUILDERS)} fixtures written to:")
    for d in OUT_DIRS:
        print(f"  {d}")


if __name__ == "__main__":
    main()
