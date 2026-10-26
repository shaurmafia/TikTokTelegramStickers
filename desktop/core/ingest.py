"""Folder-watching ingest for files saved by the Phase 1 extension.

Polls watched directories (the extension's configured output folder by
default), waits until a file is completely written (size stable across two
polls and not locked for exclusive access), and deduplicates by SHA-256.
Filename/extension are never trusted — everything is re-inspected on ingest.
"""

from __future__ import annotations

import os
import time

from .file_manager import Workspace
from .inspect import KIND_UNSUPPORTED, inspect, resolve_profile

STABLE_AFTER_S = 1.5          # size must be unchanged this long before ingest
POLL_INTERVAL_S = 0.5
MEDIA_EXTS = {".png", ".webp", ".gif", ".jpg", ".jpeg", ".apng", ".webm",
              ".mp4", ".mov", ".mkv", ".avi"}


class Inbox:
    """Watches one or more folders and yields ready, deduplicated media files."""

    def __init__(self, watch_dirs: list[str], seen_hashes: set | None = None,
                 stable_after: float = STABLE_AFTER_S):
        self.watch_dirs = [os.path.abspath(d) for d in watch_dirs]
        self.stable_after = stable_after
        self._pending: dict[str, tuple[float, int]] = {}   # path -> (mtime, size)
        self._seen_hashes: set = seen_hashes if seen_hashes is not None else set()
        self._yielded: set[str] = set()

    def scan_once(self) -> list[str]:
        """One poll pass: returns paths that are complete, recognized media,
        and not duplicates. Safe to call from a Qt timer."""
        ready: list[str] = []
        now = time.monotonic()
        for watch_dir in self.watch_dirs:
            if not os.path.isdir(watch_dir):
                continue
            try:
                entries = os.listdir(watch_dir)
            except OSError:
                continue
            for name in entries:
                path = os.path.join(watch_dir, name)
                if path in self._yielded or not os.path.isfile(path):
                    continue
                if os.path.splitext(name)[1].lower() not in MEDIA_EXTS:
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                entry = self._pending.get(path)
                if entry is None or entry["size"] != st.st_size \
                        or entry["mtime"] != st.st_mtime:
                    self._pending[path] = {"mtime": st.st_mtime,
                                           "size": st.st_size, "since": now}
                    continue
                if now - entry["since"] < self.stable_after:
                    continue
                if not self._openable_exclusively(path):
                    continue    # still being written / locked
                if not self._accept(path):
                    self._yielded.add(path)   # unrecognized: mark and skip
                    continue
                digest = Workspace.sha256(path)
                if digest in self._seen_hashes:
                    self._yielded.add(path)   # duplicate content
                    continue
                self._seen_hashes.add(digest)
                self._yielded.add(path)
                self._pending.pop(path, None)
                ready.append(path)
        return ready

    @staticmethod
    def _openable_exclusively(path: str) -> bool:
        try:
            with open(path, "rb"):
                return True
        except OSError:
            return False

    def _accept(self, path: str) -> bool:
        """Re-inspect content; trust neither name nor extension."""
        info = inspect(path)
        return info.kind != KIND_UNSUPPORTED and resolve_profile(info) is not None


class IngestQueue:
    """Bridges the Inbox to the conversion queue with debouncing."""

    def __init__(self, watch_dirs: list[str]):
        self.inbox = Inbox(watch_dirs)
        self.auto_convert = False   # always opt-in (user-controlled)

    def poll(self) -> list[str]:
        if not self.auto_convert:
            return []
        return self.inbox.scan_once()
