# Build notes — CAD-N

Reproducible packaging of the Windows `.exe` (doc section 15).

## Environment used

| Item | Value |
|---|---|
| OS | Windows 11 (x64) |
| Python | 3.14.4 (also fine on 3.11–3.13) |
| GUI | PySide6 6.11.1 (cp310-abi3 stable-ABI wheel) |
| DXF | ezdxf 1.4.4 |
| Geometry | Shapely 2.1.2 (bundled GEOS), numpy 2.4.6 |
| Packager | PyInstaller 6.20.0 |
| Installer | Inno Setup 6 (optional, not required to produce the exe) |

All runtime dependencies are pinned in `requirements.txt`; dev/build tools in
`requirements-dev.txt`. Everything installs as a **binary wheel** — no compiler
needed.

## One-time setup

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python tools\make_icon.py          REM creates cad_n\resources\icon.ico
python tools\make_fixtures.py      REM sample DXFs bundled with the app
```

## Build stages (doc 15.1)

1. **Developer run** — `python -m cad_n`, and `pytest` (65 tests must pass).
2. **One-folder build** (debuggable, used for testing):
   ```bat
   pyinstaller build\cad_n.spec --noconfirm
   ```
   Output: `dist\CAD-N\CAD-N.exe` (+ DLLs). ~150 MB folder, ~9 MB launcher.
3. **One-file build** (for handing to operators):
   ```bat
   set CADN_ONEFILE=1
   pyinstaller build\cad_n.spec --noconfirm
   ```
   Output: `dist\CAD-N.exe`. Starts a little slower (it unpacks to a temp dir).
4. **Installer** (optional): with Inno Setup 6 installed,
   ```bat
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
   ```
   Output: `release\CAD-N_Setup_<version>.exe` with Start-Menu / desktop shortcuts
   and an uninstaller.

## Verifying the build without a display

The app supports two unattended self-tests (used in CI / on the build box):

```bat
set CADN_SELFCHECK=1 & dist\CAD-N\CAD-N.exe   REM runs nest+export+reimport, exit 0 = OK
set CADN_SELFTEST=1  & dist\CAD-N\CAD-N.exe   REM shows the window then quits, exit 0 = OK
```

`SELFCHECK` proves the **frozen** Shapely/GEOS and ezdxf actually compute, not
just import. Both were confirmed returning exit code 0 on the build machine.

## Packaging gotchas & fixes

- **Shapely GEOS DLLs** — bundled via `collect_dynamic_libs("shapely")` in the
  spec. Symptom if missing: `ImportError: ... geos` at start.
- **ezdxf data files** — bundled via `collect_data_files("ezdxf")`.
- **matplotlib / Pillow are NOT shipped** — they are dev-only (benchmarks,
  rendering, icon). They are in the spec `excludes` to keep the build small.
- **PySide6 plugins** — handled by PyInstaller's PySide6 hook (includes the Qt
  `platforms` plugins, so the app finds `windows`/`offscreen`).
- **Fonts** — Qt no longer ships fonts; on a normal Windows desktop the system
  fonts are used. (The "Cannot find font directory" message only appears under
  the headless `offscreen` platform and is harmless.)
- **Antivirus / SmartScreen** — unsigned PyInstaller exes can trip SmartScreen on
  first run ("More info → Run anyway"), and some AVs flag the bootloader. For
  wide deployment, code-sign the exe.
- **First start of a one-file build** is slower because it unpacks to
  `%TEMP%`. Prefer the one-folder build for the shop floor; it starts faster.

## Clean-machine test (doc 15.2 / acceptance #13)

Copy `dist\CAD-N\` (or run the installer) onto a Windows PC **without Python**,
launch it, import a sample DXF from `cad_n\resources\sample_dxf`, run a nest,
and export. The one-folder build is fully self-contained.

## Release folder (doc 15.3)

`python tools\make_release.py` assembles:

```
release\CAD-N_<version>\
  CAD-N.exe + bundled DLLs   (the one-folder app)
  USER_GUIDE.md
  CHANGELOG.md
  README.md
  sample_dxf\
  LICENSE                    (CAD-N's MIT license)
  NOTICE                     (LGPL statement for Qt / GEOS)
  THIRD_PARTY_LICENSES.md
  LICENSES\                  (full third-party license texts)
```
