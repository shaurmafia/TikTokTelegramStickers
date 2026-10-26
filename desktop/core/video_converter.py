"""Video sticker conversion: WEBM/VP9, <= 256 KiB, <= 3 s, <= 30 fps, no audio.

Deterministic search ladder (documented in docs/QUALITY_SPEC.md):
1. cap fps at 30 (only when the source exceeds it) and duration per the
   user-selected policy (trim_first / speed_up) — never silently
2. scale to the 512 canvas (longer side exactly 512, even values)
3. two-pass ABR with an initial bitrate estimated from the size budget
4. if the output exceeds the budget: scale the bitrate by budget/actual*0.95
   and retry (up to the quality mode's attempt cap); the final fallbacks drop
   fps to 20 then 15 — each step is recorded in the report
Alpha is preserved with yuva420p when the source has alpha.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field

from .ffmpeg_locate import find_ffmpeg
from .profiles import (CANVAS, MAX_DURATION_S, MAX_FPS, VIDEO_MAX_BYTES,
                       QUALITY_MODES)


class VideoConversionError(Exception):
    pass


@dataclass
class VideoResult:
    output_path: str = ""
    warnings: list = field(default_factory=list)
    attempt_notes: list = field(default_factory=list)
    final_bitrate_bps: int = 0
    final_fps: float = 0.0
    final_duration: float = 0.0
    alpha_encoded: bool = False


def _run(args, timeout, on_kill=None):
    proc = subprocess.Popen(
        [find_ffmpeg(), "-y", "-hide_banner", "-v", "error", *args],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr = proc.communicate()
        raise VideoConversionError(f"ffmpeg timed out after {timeout}s")
    if proc.returncode != 0:
        raise VideoConversionError(
            f"ffmpeg failed: {stderr.decode(errors='replace').strip()[:300]}")
    return stderr.decode(errors="replace")


def scale_expr(width: int, height: int) -> str:
    """Scale so the longer side is exactly 512, shorter <= 512, even values."""
    if width >= height:
        return "scale='512':'-2':flags=lanczos+accurate_rnd+full_chroma_int"
    return "scale='-2':'512':flags=lanczos+accurate_rnd+full_chroma_int"


def build_filter_chain(width, height, src_fps, src_duration, policy,
                       force_fps=None) -> tuple[str, float, float, list]:
    """Return (filter_chain, out_fps, out_duration, warnings)."""
    warnings = []
    out_fps = src_fps if src_fps > 0 else 24.0
    out_duration = src_duration
    parts = []

    if force_fps is not None:
        parts.append(f"fps={force_fps}")
        out_fps = force_fps
    elif out_fps > MAX_FPS:
        parts.append(f"fps={MAX_FPS}")
        warnings.append(
            f"frame rate {src_fps:.2f} fps exceeds Telegram's {MAX_FPS} fps "
            f"limit; resampled to {MAX_FPS} fps")
        out_fps = MAX_FPS

    if out_duration > MAX_DURATION_S + 0.001:
        if policy == "speed_up":
            parts.append(f"setpts=PTS*{out_duration}/{MAX_DURATION_S}")
            warnings.append(
                f"source is {out_duration:.2f}s; sped up by "
                f"{out_duration / MAX_DURATION_S:.2f}x to fit 3.0s")
            out_duration = MAX_DURATION_S
        else:  # trim_first (default)
            parts.append(f"trim=duration={MAX_DURATION_S}")
            parts.append("setpts=PTS-STARTPTS")
            warnings.append(
                f"source is {out_duration:.2f}s; trimmed to the first 3.0s "
                f"(choose 'speed up' in settings to keep the full loop)")
            out_duration = MAX_DURATION_S

    parts.append(scale_expr(width, height))
    parts.append("format=yuva420p")
    return ",".join(parts), out_fps, out_duration, warnings


def convert_video(source_path: str, output_path: str, quality_mode: str = "balanced",
                  duration_policy: str = "trim_first",
                  source_info=None, progress=None, cancelled=None) -> VideoResult:
    mode_cfg = QUALITY_MODES[quality_mode]
    result = VideoResult()

    if source_info is None:
        from .inspect import inspect
        source_info = inspect(source_path)
    width, height = source_info.width, source_info.height
    if not width or not height:
        raise VideoConversionError("cannot determine source dimensions")

    has_alpha = source_info.has_alpha
    chain, out_fps, out_duration, warnings = build_filter_chain(
        width, height, source_info.fps, source_info.duration, duration_policy)
    result.warnings.extend(warnings)
    result.alpha_encoded = has_alpha
    result.final_fps = out_fps
    result.final_duration = out_duration

    if not has_alpha:
        result.warnings.append("source has no alpha channel")

    tmp_out = output_path + ".tmp.webm"
    log_file = output_path + ".passlog"

    def cleanup():
        for p in (tmp_out, log_file, log_file + ".tmp"):
            try:
                os.unlink(p)
            except OSError:
                pass

    # initial bitrate estimate: 97% of the budget, minus container overhead
    budget_bits = VIDEO_MAX_BYTES * 8 * 0.97
    bitrate = int(budget_bits / max(out_duration, 0.1))
    start_time = time.monotonic()
    max_seconds = 240

    # documented fps fallback order across the allowed attempts
    fps_schedule = [None] * mode_cfg.vp9_max_attempts
    if mode_cfg.vp9_max_attempts >= 3:
        fps_schedule[2:] = [20, 15][:len(fps_schedule) - 2]

    oversize_after_all = True
    for attempt in range(1, mode_cfg.vp9_max_attempts + 1):
        if cancelled and cancelled():
            cleanup()
            raise VideoConversionError("cancelled")
        if time.monotonic() - start_time > max_seconds:
            cleanup()
            raise VideoConversionError(f"exceeded {max_seconds}s processing budget")

        force_fps = fps_schedule[attempt - 1]
        chain_attempt = chain
        if force_fps is not None:
            chain_attempt = chain.replace("format=yuva420p",
                                          f"fps={force_fps},format=yuva420p")
        result.attempt_notes.append(
            f"attempt {attempt}: b:v={bitrate} "
            f"fps={force_fps or min(out_fps, MAX_FPS):.0f}")

        common = []
        if has_alpha and source_info.codec in ("vp8", "vp9"):
            # the native vp9 decoder ignores alpha; decode via libvpx
            common += ["-c:v", "libvpx-vp9"]
        common += [
            "-i", source_path,
            "-vf", chain_attempt,
            "-an", "-sn", "-dn",
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p" if has_alpha else "yuv420p",
            "-b:v", str(bitrate),
            "-row-mt", "1",
            "-deadline", "good",
            "-cpu-used", str(mode_cfg.vp9_cpu_used),
            "-passlogfile", log_file,
        ]
        if has_alpha:
            # alt-ref frames destroy VP9 alpha; alpha_mode marks the stream
            common += ["-auto-alt-ref", "0",
                       "-metadata:s:v:0", "alpha_mode=1"]

        try:
            _run([*common, "-pass", "1", "-f", "null", os.devnull],
                 timeout=max_seconds)
            _run([*common, "-pass", "2", tmp_out], timeout=max_seconds)
        except VideoConversionError:
            cleanup()
            raise

        size = os.path.getsize(tmp_out)
        result.attempt_notes[-1] += f" -> {size} bytes"
        if progress:
            progress(f"attempt {attempt}: {size} bytes")

        if size <= VIDEO_MAX_BYTES:
            oversize_after_all = False
            break
        # size search: scale bitrate down by the overshoot ratio with margin
        bitrate = max(int(bitrate * (VIDEO_MAX_BYTES / size) * 0.95), 10_000)

    if oversize_after_all:
        # attempts exhausted; keep the last output but flag it — the
        # validator decides readiness
        result.warnings.append(
            f"could not reach {VIDEO_MAX_BYTES} bytes within "
            f"{mode_cfg.vp9_max_attempts} attempts; output saved at the last "
            f"attempt's settings — requires review")

    os.replace(tmp_out, output_path)
    result.output_path = output_path
    result.final_bitrate_bps = bitrate
    cleanup()
    return result
