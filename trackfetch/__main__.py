# SPDX-License-Identifier: GPL-3.0-or-later
"""Allow ``python -m trackfetch`` and serve as the PyInstaller entry point."""

from trackfetch.cli import main

if __name__ == "__main__":
    main()
