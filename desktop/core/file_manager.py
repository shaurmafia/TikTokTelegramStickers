"""Workspace layout: source / originals / temp / output / failed / reports.

The original source bytes are ALWAYS copied unchanged into Originals before
anything else runs; nothing ever deletes or rewrites them.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import unicodedata

_INVALID = '<>:"/\\|?*'
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


class Workspace:
    def __init__(self, root: str, originals_dir=None, temp_dir=None,
                 output_dir=None, failed_dir=None, reports_dir=None):
        self.root = root
        self.originals_dir = originals_dir or os.path.join(root, "originals")
        self.temp_dir = temp_dir or os.path.join(root, "temp")
        self.output_dir = output_dir or os.path.join(root, "output")
        self.failed_dir = failed_dir or os.path.join(root, "failed")
        self.reports_dir = reports_dir or os.path.join(root, "reports")

    def ensure_dirs(self):
        for d in (self.originals_dir, self.temp_dir, self.output_dir,
                  self.failed_dir, self.reports_dir):
            os.makedirs(d, exist_ok=True)

    # -- path safety -------------------------------------------------------

    @staticmethod
    def safe_stem(filename: str) -> str:
        stem = os.path.splitext(os.path.basename(filename))[0]
        stem = unicodedata.normalize("NFC", stem)
        stem = "".join(ch for ch in stem if ord(ch) >= 32)
        for ch in _INVALID:
            stem = stem.replace(ch, "_")
        stem = re.sub(r"\.{2,}", "_", stem).strip(" .") or "sticker"
        if stem.upper() in _RESERVED:
            stem = "_" + stem
        return stem[:120]

    # -- file moves --------------------------------------------------------

    @staticmethod
    def sha256(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def preserve_original(self, source_path: str) -> str:
        """Copy the source unchanged into Originals; return the copy path."""
        self.ensure_dirs()
        stem = self.safe_stem(source_path)
        ext = os.path.splitext(source_path)[1][:16] or ".bin"
        target = os.path.join(self.originals_dir, stem + ext)
        n = 1
        while os.path.exists(target):
            target = os.path.join(self.originals_dir, f"{stem} ({n}){ext}")
            n += 1
        shutil.copy2(source_path, target)
        return target

    def unique_output_path(self, stem: str, ext: str) -> str:
        ext = ext.lstrip(".")
        target = os.path.join(self.output_dir, f"{stem}.{ext}")
        n = 1
        while os.path.exists(target):
            target = os.path.join(self.output_dir, f"{stem} ({n}).{ext}")
            n += 1
        return target

    def move_to_failed(self, path: str, stem: str, ext: str) -> str:
        os.makedirs(self.failed_dir, exist_ok=True)
        target = os.path.join(self.failed_dir, f"{stem}.{ext}")
        n = 1
        while os.path.exists(target):
            target = os.path.join(self.failed_dir, f"{stem} ({n}).{ext}")
            n += 1
        shutil.move(path, target)
        return target

    def check_free_space(self, path: str, needed_bytes: int = 50 * 1024 * 1024) -> bool:
        free = shutil.disk_usage(os.path.abspath(path)).free
        return free > needed_bytes
