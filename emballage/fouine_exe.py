"""Point d'entrée du programme Windows tout fait (Fouine.exe), fabriqué avec PyInstaller."""

import multiprocessing
import sys

from fouine.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
