"""Locate FFmpeg/ffprobe reproducibly without system changes.

Search order:
1. TTSTK_FFMPEG_DIR environment variable (directory containing the exes)
2. PATH
3. The per-user portable install used by this project:
   %LOCALAPPDATA%/TikTokStickersToolkit/ffmpeg*/bin
"""

from __future__ import annotations

import os
import shutil
import subprocess

_BIN_NAMES = {"ffmpeg": "ffmpeg.exe", "ffprobe": "ffprobe.exe"}


def _candidates(tool: str):
    name = _BIN_NAMES[tool]
    env_dir = os.environ.get("TTSTK_FFMPEG_DIR")
    if env_dir:
        yield os.path.join(env_dir, name)
    yield name  # PATH lookup
    base = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "TikTokStickersToolkit")
    if os.path.isdir(base):
        for entry in sorted(os.listdir(base), reverse=True):
            if entry.startswith("ffmpeg"):
                yield os.path.join(base, entry, "bin", name)


def find_tool(tool: str) -> str | None:
    for candidate in _candidates(tool):
        if os.path.isfile(candidate):
            return candidate
        found = shutil.which(candidate)  # bare name -> PATH
        if found:
            return found
    return None


def find_ffmpeg() -> str | None:
    return find_tool("ffmpeg")


def find_ffprobe() -> str | None:
    return find_tool("ffprobe")


def tool_version(tool_path: str) -> str | None:
    try:
        out = subprocess.run([tool_path, "-version"], capture_output=True,
                             text=True, timeout=15)
        return out.stdout.splitlines()[0] if out.stdout else None
    except Exception:
        return None
