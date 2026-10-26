"""Independent output validators. A file is Telegram-ready only when every
mandatory check here passes — never because a converter reported success."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field

from .ffmpeg_locate import find_ffprobe
from .inspect import sniff_format
from .profiles import (CANVAS, DURATION_TOLERANCE_S, STATIC_MAX_BYTES,
                       VIDEO_MAX_BYTES, MAX_FPS)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class ValidationResult:
    checks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def failed(self) -> list:
        return [c for c in self.checks if not c.passed]


def validate_static(path: str, expect_alpha: bool | None = None) -> ValidationResult:
    """True-format check via magic + Pillow; dims, alpha, size."""
    result = ValidationResult()
    size = os.path.getsize(path)
    result.checks.append(Check(
        "file_size", size <= STATIC_MAX_BYTES, f"{size} bytes (limit {STATIC_MAX_BYTES})"))

    sig = sniff_format(path)
    result.checks.append(Check(
        "container_signature", sig in ("PNG", "WEBP"), f"magic says {sig}"))

    from PIL import Image
    try:
        with open(path, "rb") as f:
            img = Image.open(f)
            img.load()
            real_format = img.format
            width, height = img.size
            mode = img.mode
    except Exception as exc:
        result.checks.append(Check("decodable", False, f"{type(exc).__name__}: {exc}"))
        return result

    result.checks.append(Check(
        "real_format", real_format in ("PNG", "WEBP"),
        f"Pillow reports {real_format}"))
    longer, shorter = max(width, height), min(width, height)
    result.checks.append(Check(
        "dimensions",
        longer == CANVAS and shorter <= CANVAS and shorter >= 1,
        f"{width}x{height} (longer side must be exactly {CANVAS})"))
    if expect_alpha:
        has_alpha = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info)
        result.checks.append(Check(
            "alpha_preserved", has_alpha,
            f"mode {mode}; source had alpha"))
    return result


def validate_video(path: str, expect_alpha: bool | None = None) -> ValidationResult:
    """ffprobe-based: container, codec, dims, duration, fps, audio, size."""
    result = ValidationResult()
    size = os.path.getsize(path)
    result.checks.append(Check(
        "file_size", size <= VIDEO_MAX_BYTES, f"{size} bytes (limit {VIDEO_MAX_BYTES})"))
    result.checks.append(Check(
        "container_signature", sniff_format(path) == "EBML(MKV/WebM)",
        f"magic says {sniff_format(path)}"))

    ffprobe = find_ffprobe()
    if ffprobe is None:
        result.checks.append(Check("ffprobe_available", False, "ffprobe not found"))
        return result
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        result.checks.append(Check("ffprobe_run", False, proc.stderr.strip()[:200]))
        return result
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos:
        result.checks.append(Check("video_stream", False, "no video stream"))
        return result
    v = videos[0]

    result.checks.append(Check(
        "container", "webm" in (data.get("format", {}).get("format_name") or ""),
        f"format_name={data.get('format', {}).get('format_name')}"))
    result.checks.append(Check(
        "video_codec", v.get("codec_name") == "vp9",
        f"codec={v.get('codec_name')}"))
    result.checks.append(Check(
        "no_audio", not audios, f"{len(audios)} audio stream(s)"))

    width, height = int(v.get("width", 0)), int(v.get("height", 0))
    longer, shorter = max(width, height), min(width, height)
    result.checks.append(Check(
        "dimensions",
        longer == CANVAS and shorter <= CANVAS and shorter % 2 == 0 and longer % 2 == 0,
        f"{width}x{height} (longer side exactly {CANVAS}, even values)"))

    try:
        duration = float(data.get("format", {}).get("duration")
                         or v.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    result.checks.append(Check(
        "duration",
        0 < duration <= 3.0 + DURATION_TOLERANCE_S,
        f"{duration:.3f}s (limit 3.0s)"))

    rate = v.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    result.checks.append(Check(
        "frame_rate", 0 < fps <= MAX_FPS + 0.01, f"{fps:.3f} fps (limit {MAX_FPS})"))

    pix_fmt = v.get("pix_fmt", "")
    result.checks.append(Check(
        "pixel_format_decodable", pix_fmt != "", f"pix_fmt={pix_fmt}"))
    # NOTE: ffprobe pix_fmt cannot verify VP9 alpha (the native decoder
    # ignores it and reports yuv420p); alpha is verified by decoding below.
    if expect_alpha:
        from .inspect import decode_alpha_frame
        result.checks.append(Check(
            "alpha_pixels_decoded", decode_alpha_frame(path),
            "decoded via libvpx decoder; source had alpha"))
    return result
