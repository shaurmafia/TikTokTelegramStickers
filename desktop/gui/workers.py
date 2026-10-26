"""Background workers: conversion jobs run off the UI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ..core.convert import run_conversion
from ..core.profiles import ConversionRequest


class ConvertJob(QObject):
    progress = Signal(str, str)          # source_path, message
    finished = Signal(object)            # ConversionReport

    def __init__(self, request: ConversionRequest):
        super().__init__()
        self.request = request
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        report = run_conversion(
            self.request,
            progress=lambda msg: self.progress.emit(self.request.source, msg),
            cancelled=lambda: self._cancel)
        self.finished.emit(report)


_LIVE_THREADS = set()   # strong refs: a GC'd QThread mid-run aborts the process


def start_job(request: ConversionRequest, on_progress, on_finished,
              pool=None) -> ConvertJob:
    job = ConvertJob(request)
    job.progress.connect(on_progress)
    job.finished.connect(on_finished)
    thread = QThread()
    job.moveToThread(thread)
    thread.started.connect(job.run)
    job.finished.connect(thread.quit)
    thread.finished.connect(lambda: _LIVE_THREADS.discard(thread))
    _LIVE_THREADS.add(thread)
    thread.start()
    return job
