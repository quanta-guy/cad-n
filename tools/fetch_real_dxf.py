"""Download real-world DXF files from public test suites for benchmarking.

These come from the test corpora of established open-source DXF libraries, so
they are genuine files authored by a range of CAD tools (AutoCAD, LibreCAD,
QCAD, etc.) -- exactly the "messy DXFs from the internet" the product must cope
with. Files land in tests/real_dxf/ with a provenance manifest.

Run:  python tools/fetch_real_dxf.py
Network failures are tolerated; whatever downloads is usable.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "real_dxf"

# (owner/repo, branch, directory) of public DXF test corpora.
SOURCES = [
    ("bjnortier/dxf", "master", "test/resources"),
    ("gdsestimating/dxf-parser", "master", "test/data"),
    ("tarikjabiri/dxf", "dev", "tests/files"),
]

UA = {"User-Agent": "CAD-N-benchmark/0.3 (+local testing)"}
MAX_BYTES = 3_000_000
MAX_PER_REPO = 8


def _get(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    total = 0
    for repo, branch, directory in SOURCES:
        api = f"https://api.github.com/repos/{repo}/contents/{directory}?ref={branch}"
        try:
            listing = json.loads(_get(api).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {repo}/{directory}: {exc}")
            continue
        if not isinstance(listing, list):
            print(f"[skip] {repo}/{directory}: unexpected response")
            continue
        got = 0
        for item in listing:
            if got >= MAX_PER_REPO:
                break
            name = item.get("name", "")
            if item.get("type") != "file" or not name.lower().endswith(".dxf"):
                continue
            if item.get("size", 0) > MAX_BYTES:
                continue
            dl = item.get("download_url")
            if not dl:
                continue
            safe = f"{repo.split('/')[0]}__{name}"
            try:
                data = _get(dl)
                (OUT / safe).write_bytes(data)
                manifest.append({"file": safe, "source_repo": repo,
                                 "source_path": f"{directory}/{name}", "bytes": len(data)})
                got += 1
                total += 1
                print(f"[ok]  {safe}  ({len(data)} bytes)")
            except Exception as exc:  # noqa: BLE001
                print(f"[fail] {dl}: {exc}")
        print(f"  -> {got} file(s) from {repo}")

    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDownloaded {total} real DXF file(s) to {OUT}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
