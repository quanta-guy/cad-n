# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CAD-N.

Build a one-folder (debuggable) build:
    pyinstaller build/cad_n.spec --noconfirm
Build a one-file build:
    set CADN_ONEFILE=1   &&   pyinstaller build/cad_n.spec --noconfirm  (Windows)

Notes / packaging gotchas (see build_notes.md):
  * Shapely ships its GEOS DLLs inside the wheel; collect_dynamic_libs grabs them.
  * ezdxf carries data files; collect_data_files includes them.
  * matplotlib is a DEV-only dependency and is excluded to keep the build small.
"""

import os

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # noqa: F821 (SPECPATH is injected)
ONEFILE = os.environ.get("CADN_ONEFILE") == "1"
ICON = os.path.join(ROOT, "cad_n", "resources", "icon.ico")

datas = []
datas += [(ICON, "cad_n/resources")]
datas += [(os.path.join(ROOT, "cad_n", "resources", "sample_dxf"),
           "cad_n/resources/sample_dxf")]
datas += collect_data_files("ezdxf")

binaries = []
binaries += collect_dynamic_libs("shapely")

hiddenimports = collect_submodules("shapely")

a = Analysis(
    [os.path.join(ROOT, "build", "launch.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter", "PyQt5", "PyQt6", "PySide2",
              "pytest", "IPython", "pandas", "scipy", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

VERSION = os.path.join(ROOT, "build", "version_info.txt")
COMMON = dict(name="CAD-N", icon=ICON, version=VERSION, console=False)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        bootloader_ignore_signals=False, strip=False, upx=False,
        runtime_tmpdir=None, **COMMON,
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, strip=False, upx=False, **COMMON)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CAD-N")
