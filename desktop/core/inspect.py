"""Media inspection: classify and measure a source file.

Static/animated images are inspected with Pillow; videos with ffprobe.
Every claim in the UI comes from this module — nothing trusts extensions.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass, field, asdict

from .ffmpeg_locate import find_ffprobe

KIND_STATIC = "static_image"
KIND_ANIMATED = "animated_image"
KIND_VIDEO = "video"
KIND_UNSUPPORTED = "unsupported"

SUPPORTED_IMAGE_FORMATS = {"PNG", "WEBP", "JPEG", "GIF"}
SUPPORTED_VIDEO_FORMATS = {"WEBM", "MP4", "MOV", "MKV", "AVI"}


@dataclass
class MediaInfo:
    path: str
    kind: str
    format: str = ""            # real container/codec format (verified)
    width: int = 0
    height: int = 0
    has_alpha: bool = False
    animated: bool = False
    duration: float = 0.0
    fps: float = 0.0
    frame_count: int = 0
    size_bytes: int = 0
    has_audio: bool = False
    pix_fmt: str = ""
    codec: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def sniff_format(path: str) -> str:
    """Magic-byte sniff for a quick unsupported check (Pillow/ffprobe decide)."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(b"\x89PNG"):
        return "PNG"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    if head[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if head[4:8] == b"ftyp":
        return "MP4-like"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "EBML(MKV/WebM)"
    return "unknown"


def inspect_image(path: str) -> MediaInfo:
    info = MediaInfo(path=path, kind=KIND_UNSUPPORTED,
                     size_bytes=os.path.getsize(path))
    sniffed = sniff_format(path)
    try:
        with open(path, "rb") as f:
            img = _pillow_open(f)
            # NOTE: all Pillow access must stay inside this with-block —
            # seeking frames after the handle closes raises.
            info.format = img.format or sniffed
            info.width, info.height = img.size
            info.has_alpha = _image_has_alpha(img)
            info.animated = bool(getattr(img, "is_animated", False))
            if info.animated:
                info.frame_count = getattr(img, "n_frames", 1)
                try:
                    info.duration = sum(
                        frame.info.get("duration", 100)
                        for frame in _iter_frames(img)) / 1000.0
                    info.fps = (info.frame_count / info.duration
                                if info.duration > 0 else 0)
                except Exception as exc:
                    info.notes.append(f"duration estimate failed: {exc}")
                info.kind = KIND_ANIMATED
            else:
                info.kind = KIND_STATIC
    except Exception as exc:
        info.notes.append(f"cannot decode: {type(exc).__name__}: {exc}")
        info.kind = KIND_UNSUPPORTED
    return info


def _pillow_open(f):
    from PIL import Image
    img = Image.open(f)
    img.load()  # force full decode now: corrupted files fail here
    return img


def _iter_frames(img):
    for i in range(getattr(img, "n_frames", 1)):
        img.seek(i)
        yield img


def _image_has_alpha(img) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P":
        return "transparency" in img.info
    return False


def inspect_video(path: str) -> MediaInfo | None:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    streams = data.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    if not vstreams:
        return None
    v = vstreams[0]
    fmt = data.get("format", {})
    info = MediaInfo(
        path=path, kind=KIND_VIDEO,
        format=(fmt.get("format_name") or "").split(",")[0],
        width=int(v.get("width", 0)), height=int(v.get("height", 0)),
        codec=v.get("codec_name", ""),
        pix_fmt=v.get("pix_fmt", ""),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        size_bytes=int(float(fmt.get("size", os.path.getsize(path)))),
        has_alpha="a" in (v.get("pix_fmt") or ""),
        animated=True,
    )
    try:
        info.duration = float(fmt.get("duration") or v.get("duration") or 0)
    except (TypeError, ValueError):
        info.duration = 0.0
    rate = v.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        info.fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        info.fps = 0.0
    nb = v.get("nb_frames")
    if nb and str(nb).isdigit():
        info.frame_count = int(nb)
    elif info.duration > 0 and info.fps > 0:
        info.frame_count = math.ceil(info.duration * info.fps)
    # ffprobe's pix_fmt comes from the native VP9 decoder, which ignores
    # VP9 alpha: verify real alpha by decoding with libvpx
    if not info.has_alpha and info.codec in ("vp8", "vp9"):
        info.has_alpha = decode_alpha_frame(path)
    return info


def decode_alpha_frame(path: str) -> bool:
    """Decode one frame with the libvpx decoder (the NATIVE vp8/vp9 decoder
    silently ignores VP9 alpha stored as BlockAdditions) and report whether
    any pixel is actually transparent."""
    import tempfile
    from .ffmpeg_locate import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return False
    tmp = tempfile.mktemp(suffix=".png")
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-c:v", "libvpx-vp9", "-i", path,
             "-frames:v", "1", "-pix_fmt", "rgba", tmp],
            capture_output=True, timeout=60)
        if proc.returncode != 0 or not os.path.exists(tmp):
            return False
        from PIL import Image
        with Image.open(tmp) as img:
            if "A" not in img.getbands():
                return False
            return img.getchannel("A").getextrema()[0] < 250
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def inspect(path: str) -> MediaInfo:
    """Top-level: classify a file as static image / animated image / video /
    unsupported, with measurements. Never raises for bad files."""
    info = MediaInfo(path=path, kind=KIND_UNSUPPORTED,
                     size_bytes=os.path.getsize(path) if os.path.exists(path) else 0)
    if not os.path.isfile(path):
        info.notes.append("file does not exist")
        return info
    sniffed = sniff_format(path)
    if sniffed in ("PNG", "WEBP", "JPEG", "GIF"):
        return inspect_image(path)
    if sniffed in ("MP4-like", "EBML(MKV/WebM)"):
        vinfo = inspect_video(path)
        if vinfo is not None and vinfo.width > 0:
            vinfo.format = vinfo.format or sniffed
            return vinfo
        info.notes.append(f"container '{sniffed}' but no decodable video stream")
        return info
    info.format = sniffed
    info.notes.append(f"unsupported magic signature: {sniffed}")
    return info


def resolve_profile(info: MediaInfo) -> str | None:
    """Which Telegram profile applies: 'static' | 'video' | None."""
    if info.kind == KIND_STATIC:
        return "static"
    if info.kind in (KIND_ANIMATED, KIND_VIDEO):
        return "video"
    return None
