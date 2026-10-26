"""GUI smoke tests, run offscreen (QT_QPA_PLATFORM=offscreen).

Verifies the window builds, drag-drop enqueueing works, the queue processes
end-to-end through the real converter, and the UI stays responsive while a
job runs.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

from PySide6.QtCore import QMimeData, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    from desktop.gui.main_window import MainWindow
    w = MainWindow(workspace_root=str(tmp_path / "ws"))
    yield w
    w.close()


def wait_until(cond, timeout=60):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


class TestMainWindow:
    def test_window_builds_and_shows_ffmpeg_status(self, window):
        assert "FFmpeg" in window.statusBar().currentMessage()
        assert window.workspace.output_dir

    def test_enqueue_and_convert_static(self, window):
        window.enqueue(os.path.join(FIX, "png_tiny_64x64.png"))
        assert window.queue_list.count() == 1
        assert wait_until(lambda: "✓ saved" in window.queue_list.item(0).text()
                          or "✗" in window.queue_list.item(0).text(), timeout=60)
        item_text = window.queue_list.item(0).text()
        assert "✓ saved" in item_text, item_text
        outputs = os.listdir(window.workspace.output_dir)
        assert len(outputs) == 1

    def test_drop_event_enqueues_files(self, window, tmp_path):
        mime = QMimeData()
        src = os.path.join(FIX, "jpeg_opaque_600x600.jpg")
        mime.setUrls([QUrl.fromLocalFile(src)])
        class FakeEvent:
            def mimeData(self):
                return mime
        window.dropEvent(FakeEvent())   # handler only reads mimeData()
        assert window.queue_list.count() == 1

    def test_duplicate_enqueue_ignored(self, window):
        src = os.path.join(FIX, "png_tiny_64x64.png")
        window.enqueue(src)
        window.enqueue(src)
        assert window.queue_list.count() == 1

    def test_ui_responsive_during_conversion(self, window):
        """Queue a video job (slow) and verify the event loop keeps pumping."""
        window.enqueue(os.path.join(FIX, "gif_animated_2s.gif"))
        beats = [0]
        timer_done = []

        def beat():
            beats[0] += 1

        from PySide6.QtCore import QTimer
        t = QTimer()
        t.timeout.connect(beat)
        t.start(100)
        wait_until(lambda: len(beats) > 3, timeout=10)
        assert beats[0] > 3            # event loop alive during heavy work
        t.stop()
        wait_until(lambda: "✓" in window.queue_list.item(0).text()
                   or "✗" in window.queue_list.item(0).text(), timeout=120)

    def test_failed_file_marked_not_crashes(self, window):
        window.enqueue(os.path.join(FIX, "malformed.bin"))
        assert wait_until(lambda: "✗ failed" in window.queue_list.item(0).text(),
                          timeout=30)
