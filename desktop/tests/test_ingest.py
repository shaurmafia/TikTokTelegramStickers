"""Ingest tests: debounce, dedupe, untrusted names, opt-in behavior."""

import os
import shutil
import time

from desktop.core.ingest import Inbox, IngestQueue

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def wait_ready(inbox, expected=1, timeout=10):
    deadline = time.monotonic() + timeout
    found = []
    while time.monotonic() < deadline and len(found) < expected:
        found.extend(inbox.scan_once())
        time.sleep(0.3)
    return found


class TestInbox:
    def test_yields_complete_media_after_debounce(self, tmp_path):
        watch = tmp_path / "watch"
        watch.mkdir()
        inbox = Inbox([str(watch)], stable_after=0.5)
        shutil.copy(os.path.join(FIX, "png_tiny_64x64.png"), watch / "a.png")
        assert inbox.scan_once() == []          # first sight: pending
        time.sleep(0.7)
        found = wait_ready(inbox, timeout=5)
        assert len(found) == 1
        assert os.path.basename(found[0]) == "a.png"

    def test_growing_file_not_yielded_until_stable(self, tmp_path):
        watch = tmp_path / "watch"
        watch.mkdir()
        inbox = Inbox([str(watch)], stable_after=0.5)
        target = watch / "g.webp"
        shutil.copy(os.path.join(FIX, "webp_static_alpha_500x512.webp"), target)
        time.sleep(0.2)
        assert inbox.scan_once() == []
        # keep modifying the file so it never looks stable
        for _ in range(4):
            with open(target, "ab") as f:
                f.write(b"x")
            inbox.scan_once()
            time.sleep(0.2)
        assert inbox.scan_once() == []          # still changing
        time.sleep(0.7)
        found = wait_ready(inbox, timeout=5)
        assert len(found) == 1

    def test_duplicate_content_skipped(self, tmp_path):
        watch = tmp_path / "watch"
        watch.mkdir()
        inbox = Inbox([str(watch)], stable_after=0.1)
        shutil.copy(os.path.join(FIX, "png_tiny_64x64.png"), watch / "one.png")
        shutil.copy(os.path.join(FIX, "png_tiny_64x64.png"), watch / "two.png")
        time.sleep(0.4)
        found = wait_ready(inbox, expected=1)
        assert len(found) == 1

    def test_untrusted_name_ignored(self, tmp_path):
        watch = tmp_path / "watch"
        watch.mkdir()
        inbox = Inbox([str(watch)], stable_after=0.1)
        shutil.copy(os.path.join(FIX, "malformed.bin"), watch / "sticker.png")
        time.sleep(0.4)
        found = wait_ready(inbox)
        assert found == []               # .png name, garbage content

    def test_unwatched_ext_skipped(self, tmp_path):
        watch = tmp_path / "watch"
        watch.mkdir()
        inbox = Inbox([str(watch)], stable_after=0.1)
        shutil.copy(os.path.join(FIX, "png_tiny_64x64.png"), watch / "x.txt")
        time.sleep(0.4)
        assert wait_ready(inbox) == []

    def test_missing_watch_dir_is_safe(self, tmp_path):
        inbox = Inbox([str(tmp_path / "nope")])
        assert inbox.scan_once() == []


class TestIngestQueue:
    def test_auto_convert_opt_in(self, tmp_path):
        q = IngestQueue([str(tmp_path)])
        assert q.poll() == []            # off by default
        q.auto_convert = True
        assert q.poll() == []            # on, but nothing to see
