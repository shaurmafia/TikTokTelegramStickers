"""Orchestrator + file-management tests: originals untouched, failure paths,
unicode/duplicate names, traversal attempts, reports."""

import json
import os

from desktop.core.convert import run_conversion
from desktop.core.file_manager import Workspace
from desktop.core.profiles import ConversionRequest

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def make_request(ws, source, **kw):
    return ConversionRequest(
        source=source, profile="auto",
        output_dir=ws.output_dir, temp_dir=ws.temp_dir,
        originals_dir=ws.originals_dir, failed_dir=ws.failed_dir,
        reports_dir=ws.reports_dir, **kw)


class TestOriginals:
    def test_original_preserved_byte_for_byte(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        ws.ensure_dirs()
        src = os.path.join(ws.temp_dir, "in.png")
        with open(os.path.join(FIX, "png_tiny_64x64.png"), "rb") as f:
            data = f.read()
        with open(src, "wb") as f:
            f.write(data)
        report = run_conversion(make_request(ws, src))
        assert report.status == "ok"
        with open(report.original_copy_path, "rb") as f:
            assert f.read() == data
        with open(src, "rb") as f:            # source itself untouched
            assert f.read() == data
        assert report.source_sha256 == Workspace.sha256(src)
        assert report.output_sha256 == Workspace.sha256(report.output_path)


class TestFailurePaths:
    def test_malformed_file_fails_gracefully(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        report = run_conversion(make_request(ws, os.path.join(FIX, "malformed.bin")))
        assert report.status == "failed"
        assert "unsupported" in report.error.lower()
        assert not report.output_path or not os.path.exists(report.output_path)

    def test_truncated_png_fails(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        report = run_conversion(make_request(ws, os.path.join(FIX, "truncated_png.png")))
        assert report.status == "failed"

    def test_missing_file_fails(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        report = run_conversion(make_request(ws, str(tmp_path / "nope.png")))
        assert report.status == "failed"
        assert report.original_copy_path == ""

    def test_report_json_written_even_on_failure(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        run_conversion(make_request(ws, os.path.join(FIX, "malformed.bin")))
        reports = os.listdir(ws.reports_dir)
        assert reports
        with open(os.path.join(ws.reports_dir, reports[0]), encoding="utf-8") as f:
            data = json.load(f)
        assert data["status"] == "failed"


class TestNaming:
    def test_unicode_filename(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        ws.ensure_dirs()
        src = os.path.join(ws.temp_dir, "стикер — тест #1.png")
        with open(os.path.join(FIX, "png_tiny_64x64.png"), "rb") as f:
            data = f.read()
        with open(src, "wb") as f:
            f.write(data)
        report = run_conversion(make_request(ws, src))
        assert report.status == "ok"
        assert os.path.exists(report.output_path)

    def test_duplicate_outputs_get_suffix(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        src = os.path.join(FIX, "png_tiny_64x64.png")
        r1 = run_conversion(make_request(ws, src))
        r2 = run_conversion(make_request(ws, src))
        assert r1.output_path != r2.output_path
        assert os.path.exists(r1.output_path) and os.path.exists(r2.output_path)

    def test_traversal_like_name_sanitized(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        stem = Workspace.safe_stem(r"..\..\evil<>file")
        assert ".." not in stem
        assert "/" not in stem and "\\" not in stem and "<" not in stem

    def test_reserved_name_prefixed(self):
        assert Workspace.safe_stem("CON") == "_CON"


class TestCancellation:
    def test_cancelled_before_start(self, tmp_path):
        ws = Workspace(str(tmp_path / "ws"))
        report = run_conversion(
            make_request(ws, os.path.join(FIX, "png_tiny_64x64.png")),
            cancelled=lambda: True)
        assert report.status == "cancelled"
