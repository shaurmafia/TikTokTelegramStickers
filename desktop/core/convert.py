"""Conversion orchestrator: inspect -> preserve original -> convert ->
validate -> file placement + report. One public function per job."""

from __future__ import annotations

import os

from .file_manager import Workspace
from .inspect import (KIND_STATIC, KIND_UNSUPPORTED, decode_alpha_frame,
                      inspect, resolve_profile)
from .profiles import ConversionRequest
from .report import ConversionReport
from .static_converter import StaticConversionError, convert_static
from .validate import ValidationResult, validate_static, validate_video
from .video_converter import VideoConversionError, convert_video


class Cancelled(Exception):
    pass


def run_conversion(request: ConversionRequest, progress=None,
                   cancelled=None) -> ConversionReport:
    """Convert one file. Returns a full report; never raises for bad media
    (failures land in the report and the failed/ dir)."""
    import time
    started = time.monotonic()
    report = ConversionReport(
        source_path=request.source, profile=request.profile,
        quality_mode=request.quality_mode)
    ws = Workspace(
        request.output_dir and os.path.dirname(request.output_dir) or _root_of(request),
        originals_dir=request.originals_dir, temp_dir=request.temp_dir,
        output_dir=request.output_dir, failed_dir=request.failed_dir,
        reports_dir=request.reports_dir)
    ws.ensure_dirs()

    try:
        if not os.path.isfile(request.source):
            raise FileNotFoundError(f"source file not found: {request.source}")
        stem = Workspace.safe_stem(request.source)
        report.original_copy_path = ws.preserve_original(request.source)
        report.source_sha256 = Workspace.sha256(request.source)

        info = inspect(request.source)
        report.source_info = info.to_dict()
        profile_kind = resolve_profile(info)

        if cancelled and cancelled():
            raise Cancelled()
        if info.kind == KIND_UNSUPPORTED:
            raise ValueError(
                f"unsupported file: {info.format or 'unknown signature'} "
                f"({'; '.join(info.notes)})")
        if not ws.check_free_space(ws.output_dir):
            raise OSError("insufficient free disk space in the output folder")

        if profile_kind == "static":
            report.profile = "static"
            out = ws.unique_output_path(stem, "webp")
            res = convert_static(request.source, out, request.quality_mode,
                                 progress=progress)
            report.output_path = res.output_path
            report.warnings = res.warnings
            report.attempt_notes = res.attempt_notes
            validation = validate_static(
                res.output_path, expect_alpha=info.has_alpha)

        elif profile_kind == "video":
            report.profile = "video"
            out = ws.unique_output_path(stem, "webm")
            res = convert_video(request.source, out, request.quality_mode,
                                request.duration_policy, source_info=info,
                                progress=progress, cancelled=cancelled)
            report.output_path = res.output_path
            report.warnings = res.warnings
            report.attempt_notes = res.attempt_notes
            validation = validate_video(
                res.output_path, expect_alpha=info.has_alpha)
            if (info.has_alpha and validation.ok
                    and not decode_alpha_frame(res.output_path)):
                validation.checks.append(
                    ValidationResult().checks.__class__(
                        "alpha_pixels_decoded", False,
                        "VP9 alpha stream exists but no transparent pixels "
                        "decoded — possible alpha loss"))
            for check in validation.checks:
                if not check.passed:
                    report.warnings.append(f"validation: {check.name}: {check.detail}")
        else:
            raise ValueError(f"unclassified media kind: {info.kind}")

        report.validation = {
            "ok": validation.ok,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                       for c in validation.checks],
            "warnings": validation.warnings,
        }
        report.telegram_ready = validation.ok
        report.status = "ok" if validation.ok else "needs_review"

        if not validation.ok and ws.failed_dir:
            ext = os.path.splitext(report.output_path)[1].lstrip(".")
            os.makedirs(ws.failed_dir, exist_ok=True)
            report.output_path = ws.move_to_failed(report.output_path, stem, ext)

    except Cancelled:
        report.status = "cancelled"
        report.error = "cancelled by user"
    except (StaticConversionError, VideoConversionError, ValueError, OSError) as exc:
        report.status = "failed"
        report.error = str(exc)
        report.warnings.append(report.error)
    except Exception as exc:  # noqa: BLE001 — report everything, crash nothing
        report.status = "failed"
        report.error = f"unexpected: {type(exc).__name__}: {exc}"

    report.duration_s = round(time.monotonic() - started, 3)
    if report.output_path and os.path.exists(report.output_path):
        report.output_sha256 = Workspace.sha256(report.output_path)
    report.save(ws.reports_dir)
    return report


def _root_of(request: ConversionRequest) -> str:
    base = request.output_dir or request.temp_dir or request.originals_dir
    if base:
        parent = os.path.dirname(base)
        return parent if os.path.basename(parent) else base
    return os.path.join(os.path.expanduser("~"), "TikTokStickers")
