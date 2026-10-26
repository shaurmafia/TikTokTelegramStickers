"""Telegram sticker output profiles and quality modes.

Hard limits (Telegram Bot API / sticker requirements, Phase 2 spec):
- static stickers: PNG or WEBP, <= 512x512 with the LONGER side exactly 512,
  <= 512 KiB, alpha preserved
- video stickers: WEBM/VP9, <= 512x512 (longer side exactly 512), <= 3.0 s,
  <= 30 fps, no audio, <= 256 KiB, optional VP9 alpha
- TGS is intentionally NOT offered as an output (see docs/KNOWN_LIMITATIONS)
"""

from __future__ import annotations

from dataclasses import dataclass, field

STATIC_MAX_BYTES = 512 * 1024
VIDEO_MAX_BYTES = 256 * 1024
CANVAS = 512
MAX_DURATION_S = 3.0
MAX_FPS = 30
DURATION_TOLERANCE_S = 0.06


@dataclass
class QualityMode:
    name: str
    # WEBP lossy quality ladder for static fallback (descending)
    webp_ladder: tuple
    # libvpx-vp9 cpu-used: lower = slower/better; bitrate search attempts
    vp9_cpu_used: int
    vp9_max_attempts: int
    description: str


QUALITY_MODES = {
    "quality_first": QualityMode(
        "quality_first", (95, 90, 85, 80, 70, 60, 50), 2, 4,
        "Best perceptual quality; slower encode, may fail the size limit "
        "on complex sources (then flagged for review)."),
    "balanced": QualityMode(
        "balanced", (90, 82, 72, 60, 50, 40), 3, 4,
        "Good quality with reliable size compliance; slight quality loss "
        "on busy animations."),
    "size_first": QualityMode(
        "size_first", (80, 70, 60, 50, 40, 30), 4, 3,
        "Guaranteed-small outputs first; visibly softer detail on complex "
        "sources."),
}


@dataclass
class StaticProfile:
    name: str = "static_sticker"
    allowed_formats: tuple = ("PNG", "WEBP")
    max_bytes: int = STATIC_MAX_BYTES


@dataclass
class VideoProfile:
    name: str = "video_sticker"
    container: str = "webm"
    codec: str = "vp9"
    max_bytes: int = VIDEO_MAX_BYTES
    max_duration: float = MAX_DURATION_S
    max_fps: int = MAX_FPS
    allow_alpha: bool = True


@dataclass
class ConversionRequest:
    """Everything deterministic about one conversion job."""
    source: str
    profile: str                  # "static" | "video" (auto-resolved later)
    quality_mode: str = "balanced"
    duration_policy: str = "trim_first"   # trim_first | speed_up (video only)
    output_dir: str = ""
    temp_dir: str = ""
    originals_dir: str = ""
    failed_dir: str = ""
    reports_dir: str = ""
    extra_warnings: list = field(default_factory=list)
