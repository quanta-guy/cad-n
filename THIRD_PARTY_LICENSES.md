# Third-Party Licenses

CAD-N is licensed under the MIT License (see [`LICENSE`](LICENSE)). It depends on,
and its packaged builds redistribute, the third-party open-source components listed
below. Each retains its own license; full texts are in the [`LICENSES/`](LICENSES/)
folder where noted.

## Components redistributed in the packaged application (the `.exe`)

| Component | Version | License | Full text |
|---|---|---|---|
| [ezdxf](https://github.com/mozman/ezdxf) | 1.4.4 | MIT | [`LICENSES/ezdxf-LICENSE.txt`](LICENSES/ezdxf-LICENSE.txt) |
| [NumPy](https://numpy.org/) | 2.4.6 | BSD-3-Clause | [`LICENSES/numpy-LICENSE.txt`](LICENSES/numpy-LICENSE.txt) |
| [Shapely](https://github.com/shapely/shapely) | 2.1.2 | BSD-3-Clause | [`LICENSES/shapely-LICENSE.txt`](LICENSES/shapely-LICENSE.txt) |
| [GEOS](https://libgeos.org/) (bundled inside the Shapely wheel) | — | **LGPL-2.1** | [`LICENSES/GEOS-LICENSE-LGPLv2.1.txt`](LICENSES/GEOS-LICENSE-LGPLv2.1.txt) |
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | 6.11.1 | **LGPL-3.0** | see "LGPL components" below |
| [shiboken6](https://www.qt.io/qt-for-python) | 6.11.1 | LGPL-3.0 | see "LGPL components" below |

Copyright holders (permissive components):

- **ezdxf** — Copyright (c) 2020 Manfred Moitzi (MIT)
- **NumPy** — Copyright (c) 2005-2025, NumPy Developers (BSD-3-Clause)
- **Shapely** — Copyright (c) 2007, Sean C. Gillies; 2019, Casper van der Wel; 2007-2022, Shapely Contributors (BSD-3-Clause)

## LGPL components (Qt / PySide6 and GEOS)

CAD-N uses **PySide6 (Qt)** and, via Shapely, the **GEOS** geometry engine. Both are
licensed under the GNU Lesser General Public License and are used **as dynamically
linked shared libraries** — CAD-N's own MIT-licensed source is not a derivative work
of them.

In packaged builds these libraries ship as separate, replaceable shared libraries
(`*.dll`). In keeping with the LGPL you may obtain the corresponding library source
and substitute your own compatible build of either library:

- **Qt / PySide6** — LGPL-3.0. Source and license: https://www.qt.io/licensing and
  https://download.qt.io/. The full GNU LGPL-3.0 text: https://www.gnu.org/licenses/lgpl-3.0.html
  To replace it, install your own copy of PySide6/Qt (`pip install PySide6`) or swap the
  bundled Qt DLLs in the application folder.
- **GEOS** — LGPL-2.1. Source: https://github.com/libgeos/geos. The bundle notice and
  license text are in [`LICENSES/GEOS-LICENSE-LGPLv2.1.txt`](LICENSES/GEOS-LICENSE-LGPLv2.1.txt).
  To replace it, install your own Shapely/GEOS build or swap the bundled `geos*.dll`.

See [`NOTICE`](NOTICE) for the short-form LGPL statement that accompanies binary releases.

## Build- and test-only tools (NOT redistributed)

These are used only to develop, test, or package CAD-N and are **not** included in the
shipped application, so their licenses impose no obligation on end users:

| Tool | License | Note |
|---|---|---|
| PyInstaller | GPL-2.0 **with bootloader exception** | The exception explicitly leaves apps it builds unencumbered. |
| pytest | MIT | test runner |
| matplotlib | PSF/BSD-compatible | dev visualization only (excluded from the build) |
| Pillow | MIT-CMU | icon generation only (excluded from the build) |

_Regenerate this inventory after a dependency bump by re-copying the texts in
`LICENSES/` from the active virtualenv's `*.dist-info/licenses/` folders._
