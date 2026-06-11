"""Frozen-app entry point for PyInstaller.

Uses an absolute import (PyInstaller runs the entry script as ``__main__``, so a
package-relative import would fail here)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from cad_n.main import main

    sys.exit(main())
