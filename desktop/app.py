"""Application entry point: python -m desktop.app"""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("TikTok DM Sticker Saver")
    root = None
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        root = sys.argv[1]
    window = MainWindow(workspace_root=root)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
