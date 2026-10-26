"""Main window: drag-and-drop, queue, previews, quality controls, ingest."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget)

from ..core.file_manager import Workspace
from ..core.ffmpeg_locate import find_ffmpeg, tool_version
from ..core.inspect import inspect
from ..core.ingest import IngestQueue
from ..core.profiles import ConversionRequest, QUALITY_MODES
from ..core.ffmpeg_locate import find_ffmpeg
from .workers import start_job

APP_TITLE = "TikTok DM Sticker Saver — Converter (Phase 2, WIP)"
STATUS_QUEUED, STATUS_WORKING = "queued", "working…"


class MainWindow(QMainWindow):
    def __init__(self, workspace_root=None):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1000, 640)

        default_root = workspace_root or os.path.join(
            os.path.expanduser("~"), "TikTokStickers")
        self.workspace = Workspace(default_root)
        self.workspace.ensure_dirs()
        self.ingest = IngestQueue([self.workspace.originals_dir])

        self._jobs = {}          # source path -> ConvertJob
        self._busy = False
        self._queue: list[str] = []

        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_inbox)
        self._poll_timer.start(1000)
        self._pump()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # left: drop zone + queue
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.drop_label = QLabel(
            "Drag & drop sticker files or folders here\n"
            "(PNG · WEBP · JPEG · GIF · APNG · WEBM · MP4)")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setMinimumHeight(70)
        self.drop_label.setStyleSheet(
            "border: 2px dashed #555; border-radius: 8px; color: #888;")
        self.drop_label.setAcceptDrops(False)
        left_layout.addWidget(self.drop_label)
        self.queue_list = QListWidget()
        left_layout.addWidget(self.queue_list)

        controls = QFormLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(list(QUALITY_MODES))
        self.quality_combo.setCurrentText("balanced")
        controls.addRow("Quality mode:", self.quality_combo)
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["trim_first", "speed_up"])
        controls.addRow("Over-3s policy:", self.duration_combo)
        self.auto_ingest = QCheckBox("Auto-ingest files from the extension "
                                     "output folder (watched)")
        controls.addRow(self.auto_ingest)
        left_layout.addLayout(controls)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Convert queue")
        self.start_btn.clicked.connect(self._pump)
        self.cancel_btn = QPushButton("Cancel current")
        self.cancel_btn.clicked.connect(self._cancel_current)
        self.open_out_btn = QPushButton("Open output folder")
        self.open_out_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(self.workspace.output_dir)))
        for b in (self.start_btn, self.cancel_btn, self.open_out_btn):
            buttons.addWidget(b)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        # right: preview + metadata
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.preview = QLabel("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(280)
        self.preview.setStyleSheet("background: #14141a; border-radius: 8px;")
        right_layout.addWidget(self.preview)
        self.meta_view = QTextEdit()
        self.meta_view.setReadOnly(True)
        right_layout.addWidget(self.meta_view)
        self.open_src_btn = QPushButton("Open source in default player")
        self.open_src_btn.clicked.connect(self._open_source)
        right_layout.addWidget(self.open_src_btn)
        splitter.addWidget(right)
        splitter.setSizes([480, 520])
        self.setAcceptDrops(True)
        self._selected_source = None

        # ffmpeg status in the status bar
        ffmpeg = find_ffmpeg()
        ver = tool_version(ffmpeg) if ffmpeg else None
        self.statusBar().showMessage(
            f"FFmpeg: {ver or 'NOT FOUND — see README (installation)'}")

    # ------------------------------------------------------------- events

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    self.enqueue(os.path.join(path, name))
            elif path:
                self.enqueue(path)

    # ------------------------------------------------------------ queue

    def enqueue(self, path: str):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return
        if any(self.queue_list.item(i).data(Qt.UserRole) == path
               for i in range(self.queue_list.count())):
            return
        item = QListWidgetItem(f"{os.path.basename(path)}  —  {STATUS_QUEUED}")
        item.setData(Qt.UserRole, path)
        self.queue_list.addItem(item)
        self._queue.append(path)
        self._pump()

    def _set_item_text(self, source, text):
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            if item.data(Qt.UserRole) == source:
                item.setText(f"{os.path.basename(source)}  —  {text}")
                return

    def _pump(self):
        """Start the next queued job when idle (one at a time: deterministic,
        keeps UI responsive, avoids CDN/encoder thrash)."""
        if self._busy or not self._queue:
            return
        source = self._queue.pop(0)
        self._busy = True
        self._set_item_text(source, STATUS_WORKING)
        request = ConversionRequest(
            source=source, profile="auto",
            quality_mode=self.quality_combo.currentText(),
            duration_policy=self.duration_combo.currentText(),
            output_dir=self.workspace.output_dir,
            temp_dir=self.workspace.temp_dir,
            originals_dir=self.workspace.originals_dir,
            failed_dir=self.workspace.failed_dir,
            reports_dir=self.workspace.reports_dir,
        )
        self._jobs[source] = start_job(
            request,
            on_progress=lambda src, msg: self._set_item_text(src, msg),
            on_finished=self._job_done)

    def _job_done(self, report):
        self._busy = False
        self._jobs.pop(report.source_path, None)
        status_map = {"ok": "✓ saved", "needs_review": "⚠ needs review",
                      "failed": "✗ failed", "cancelled": "cancelled"}
        text = status_map.get(report.status, report.status)
        detail = ""
        if report.status == "ok":
            detail = f" → {os.path.basename(report.output_path)}"
        warn = ""
        if report.warnings:
            warn = f"  [{len(report.warnings)} warning(s)]"
        self._set_item_text(report.source_path, f"{text}{detail}{warn}")
        self._show_report(report)
        self._pump()

    def _cancel_current(self):
        for job in self._jobs.values():
            job.cancel()

    def _poll_inbox(self):
        if self.auto_ingest.isChecked():
            for path in self.ingest.inbox.scan_once():
                self.enqueue(path)
                self._set_item_text(path, "ingested from extension folder")

    # ----------------------------------------------------------- preview

    def _show_source_info(self, source):
        self._selected_source = source
        info = inspect(source)
        self.meta_view.setPlainText(
            f"SOURCE: {os.path.basename(source)}\n"
            f"kind: {info.kind}  format: {info.format}\n"
            f"size: {info.width}x{info.height}  alpha: {info.has_alpha}\n"
            f"duration: {info.duration:.2f}s  fps: {info.fps:.2f}  "
            f"frames: {info.frame_count}\n"
            f"bytes: {info.size_bytes}\n"
            + ("\n".join("note: " + n for n in info.notes)))
        self._render_preview(source, info)

    def _render_preview(self, source, info):
        self.preview.setText("preview")
        if info.kind in ("static_image",):
            self.preview.setPixmap(QPixmap(source).scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        elif info.kind in ("animated_image", "video"):
            frame = self._extract_first_frame(source)
            if frame and os.path.exists(frame):
                self.preview.setPixmap(QPixmap(frame).scaled(
                    self.preview.size(), Qt.KeepAspectRatio,
                    Qt.SmoothTransformation))
                self.preview.setToolTip(
                    "first frame shown; use 'Open source in default player' "
                    "for the animation")
            else:
                self.preview.setText("no preview available")

    @staticmethod
    def _extract_first_frame(source):
        import subprocess
        import tempfile
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return None
        tmp = tempfile.mktemp(prefix="ttstk-prev-", suffix=".png")
        try:
            subprocess.run([ffmpeg, "-y", "-v", "error", "-i", source,
                            "-frames:v", "1", tmp], capture_output=True,
                           timeout=30)
            return tmp
        except Exception:
            return None

    def _show_report(self, report):
        lines = [f"OUTPUT REPORT — {os.path.basename(report.source_path)}",
                 f"status: {report.status}  "
                 f"(telegram_ready={report.telegram_ready})"]
        if report.output_path:
            lines.append(f"output: {report.output_path}")
        if report.error:
            lines.append(f"error: {report.error}")
        for w in report.warnings:
            lines.append(f"warning: {w}")
        for check in report.validation.get("checks", []):
            mark = "✓" if check["passed"] else "✗"
            lines.append(f"  {mark} {check['name']}: {check['detail']}")
        self.meta_view.append("\n" + "\n".join(lines))
        if report.status == "failed":
            # non-blocking: a modal per failure would wedge batch runs
            self.statusBar().showMessage(
                f"FAILED: {os.path.basename(report.source_path)} — "
                f"{report.error}", 10000)

    def _open_source(self):
        if self._selected_source:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._selected_source))
