#!/usr/bin/env python3
"""Build a standalone Windows x64 executable with PyInstaller.

Usage:
    python tools/build_windows.py

Output: dist/TikTokDMStickerSaver/ (folder build — start with the .exe).
FFmpeg is NOT bundled: place a portable FFmpeg build in
%LOCALAPPDATA%\\TikTokStickersToolkit\\ffmpeg*/bin or on PATH (the app
locates it the same way in packaged and source form).
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    subprocess.run([sys.executable, "-m", "pip", "show", "pyinstaller"],
                   capture_output=True, check=False)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "TikTokDMStickerSaver",
        "--windowed",
        "--add-data", os.path.join(ROOT, "extension") + os.pathsep + "extension",
        "--collect-submodules", "PySide6",
        os.path.join(ROOT, "desktop", "app.py"),
    ]
    print(" ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
