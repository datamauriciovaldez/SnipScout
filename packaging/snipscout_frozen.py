"""Entry point for the experimental PyInstaller build: no arguments = open the app window."""

import sys

from snipscout.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["ui"]))
