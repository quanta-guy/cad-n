"""Enable `python -m cad_n`."""

import sys

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    from .main import main

    sys.exit(main())
