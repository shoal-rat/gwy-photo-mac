"""PyInstaller entry point. --cli keeps command-line processing available in the app."""

import sys

if "--cli" in sys.argv:
    sys.argv.remove("--cli")
    from gwy_photo_mac.cli import main
else:
    from gwy_photo_mac.gui import main

raise SystemExit(main())
