"""Static sticker conversion: PNG / lossless-or-lossy WEBP, <= 512 KiB.

Canvas rule: the longer side becomes exactly 512 (up or down — Telegram
requires it), the shorter side scales proportionally and stays <= 512.
Alpha edges are handled with premultiplied Lanczos resampling to avoid
dark/bright fringes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .profiles import CANVAS, STATIC_MAX_BYTES, QUALITY_MODES


class StaticConversionError(Exception):
    pass


@dataclass
class StaticResult:
    output_path: str = ""
    format: str = ""            # "PNG" | "WEBP"
    quality: int | None = None  # WEBP lossy quality, None = lossless
    lossless: bool = True
    resized: bool = False
    upscaled: bool = False
    warnings: list = field(default_factory=list)
    attempt_notes: list = field(default_factory=list)


def target_dimensions(width: int, height: int) -> tuple[int, int, bool, bool]:
    """Return (w, h, resized, upscaled) under the 512-canvas rule."""
    longer = max(width, height)
    if longer == CANVAS:
        return width, height, False, False
    scale = CANVAS / longer
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    # keep the longer side exact after rounding
    if max(new_w, new_h) != CANVAS:
        if width >= height:
            new_w = CANVAS
        else:
            new_h = CANVAS
    return new_w, new_h, True, longer < CANVAS


def _resize_premultiplied(img, new_size):
    """Lanczos resize in premultiplied alpha space (no transparent fringes)."""
    from PIL import Image, ImageChops, ImageMath

    def unmul(channel, alpha):
        # +1 when alpha==0 avoids division by zero; those pixels are fully
        # transparent so the color value is irrelevant
        expr = lambda ev: ImageMath.ops["convert"](
            ev["chan"] * 255 / (ev["alpha"] + (ev["alpha"] == 0)), "L")  # noqa: E731
        if hasattr(ImageMath, "lambda_eval"):
            return ImageMath.lambda_eval(expr, chan=channel, alpha=alpha)
        return ImageMath.eval("convert(chan * 255 / (alpha + (alpha == 0)), 'L')",
                              chan=channel, alpha=alpha)

    img = img.convert("RGBA")
    r, g, b, a = img.split()
    # ImageChops.multiply == (chan * alpha) / 255 — exact premultiply
    premul = Image.merge("RGBA", (ImageChops.multiply(r, a),
                                  ImageChops.multiply(g, a),
                                  ImageChops.multiply(b, a), a))
    premul = premul.resize(new_size, Image.LANCZOS)
    r2, g2, b2, a2 = premul.split()
    out = Image.merge("RGBA", (unmul(r2, a2), unmul(g2, a2), unmul(b2, a2), a2))
    return out


def _encode(img, fmt: str, quality=None) -> bytes:
    import io
    buf = io.BytesIO()
    if fmt == "WEBP":
        kwargs = {"lossless": quality is None, "method": 6}
        if quality is not None:
            kwargs["quality"] = quality
        img.save(buf, "WEBP", **kwargs)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def convert_static(source_path: str, output_path: str, quality_mode: str = "balanced",
                   progress=None) -> StaticResult:
    from PIL import Image
    mode_cfg = QUALITY_MODES[quality_mode]
    result = StaticResult()

    with open(source_path, "rb") as f:
        img = Image.open(f)
        img.load()
    width, height = img.size
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info)

    new_size = (width, height)
    new_w, new_h, resized, upscaled = target_dimensions(width, height)
    if resized:
        img = _resize_premultiplied(img, (new_w, new_h))
        result.resized = True
        if upscaled:
            result.warnings.append(
                f"source {width}x{height} is smaller than Telegram's 512 canvas; "
                f"upscaled to {new_w}x{new_h}")
        else:
            result.warnings.append(
                f"downscaled {width}x{height} -> {new_w}x{new_h} (longer side must be 512)")
    if not has_alpha:
        result.warnings.append("source has no alpha channel")

    # Candidate ladder, deterministic. Both lossless candidates first; the
    # smaller lossless one wins if it fits. Otherwise lossy WEBP from the
    # mode's ladder, highest quality that fits.
    candidates = []
    webp_lossless = _encode(img, "WEBP")
    candidates.append(("WEBP", None, webp_lossless, True))
    png_bytes = _encode(img, "PNG")
    candidates.append(("PNG", None, png_bytes, True))

    chosen = None
    for fmt, quality, data, lossless in candidates:
        result.attempt_notes.append(f"{fmt} lossless: {len(data)} bytes")
        if len(data) <= STATIC_MAX_BYTES:
            chosen = (fmt, quality, data, lossless)
            break
    if chosen is None:
        # pick the smaller lossless as the quality reference, then ladder
        for quality in mode_cfg.webp_ladder:
            data = _encode(img, "WEBP", quality)
            result.attempt_notes.append(f"WEBP q{quality}: {len(data)} bytes")
            if progress:
                progress(f"WEBP q{quality}: {len(data)} bytes")
            if len(data) <= STATIC_MAX_BYTES:
                chosen = ("WEBP", quality, data, False)
                break
            if quality == mode_cfg.webp_ladder[-1]:
                chosen = ("WEBP", quality, data, False)
                result.warnings.append(
                    f"could not reach {STATIC_MAX_BYTES} bytes without heavy "
                    f"loss; saved at minimum ladder quality {quality} — review "
                    f"the result")
    if chosen is None:
        raise StaticConversionError("no encoding candidate produced output")

    fmt, quality, data, lossless = chosen
    result.format, result.quality, result.lossless = fmt, quality, lossless
    tmp = output_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, output_path)
    result.output_path = output_path
    return result
