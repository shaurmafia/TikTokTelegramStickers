#!/usr/bin/env python3
"""Generate synthetic test fixtures for Phase 2 (desktop converter).

All fixtures are deterministic and regenerable; none contain user data.
Animated fixtures are encoded with the FFmpeg binary located the same way
the desktop app locates it (see desktop/core/ffmpeg_locate.py).
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "desktop"))

from desktop.core.ffmpeg_locate import find_ffmpeg, find_ffprobe  # noqa: E402

FIXTURES = os.path.join(ROOT, "desktop", "tests", "fixtures")

RED = (204, 34, 68)
BLUE = (34, 102, 204)
GREEN = (34, 204, 136)


def gradient_with_hole(size, color, hole):
    """RGBA image with hard alpha edges (circle hole) to expose fringing."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", size, color + (255,))
    d = ImageDraw.Draw(img)
    for i in range(size[0]):  # diagonal stripes for motion/color detail
        d.line([(i, 0), (0, i)], fill=(255, 255, 255, 180), width=2)
    d.ellipse(hole, fill=(0, 0, 0, 0))
    return img


def make_static():
    from PIL import Image
    gradient_with_hole((700, 500), RED, (250, 150, 450, 350)).save(
        os.path.join(FIXTURES, "png_landscape_700x500.png"))
    gradient_with_hole((300, 900), BLUE, (100, 350, 200, 550)).save(
        os.path.join(FIXTURES, "png_portrait_300x900.png"))
    gradient_with_hole((64, 64), GREEN, (20, 20, 44, 44)).save(
        os.path.join(FIXTURES, "png_tiny_64x64.png"))
    gradient_with_hole((2000, 2000), RED, (800, 800, 1200, 1200)).save(
        os.path.join(FIXTURES, "png_large_2000x2000.png"))
    # opaque JPEG (no alpha)
    gradient_with_hole((600, 600), BLUE, (200, 200, 400, 400)).convert(
        "RGB").save(os.path.join(FIXTURES, "jpeg_opaque_600x600.jpg"), quality=92)
    # lossless WEBP with alpha
    gradient_with_hole((500, 512), GREEN, (150, 150, 350, 350)).save(
        os.path.join(FIXTURES, "webp_static_alpha_500x512.webp"), lossless=True)


def make_gif():
    from PIL import Image
    frames = []
    for i in range(40):  # 2.0 s at 50 ms/frame
        color = RED if i % 20 < 10 else BLUE
        img = gradient_with_hole((400, 400), color, (60 + i * 5, 150, 200 + i * 5, 290))
        # hard transparency: pixels below the circle are fully transparent
        alpha = img.getchannel("A").point(lambda a: 0 if a < 250 else 255)
        img.putalpha(alpha)
        frames.append(img)
    frames[0].save(os.path.join(FIXTURES, "gif_animated_2s.gif"),
                   save_all=True, append_images=frames[1:], duration=50, loop=0,
                   disposal=2, transparency=0)


def make_apng():
    from PIL import Image
    frames = []
    for i in range(24):  # 1.2 s at 50 ms
        frames.append(gradient_with_hole((300, 300), GREEN if i % 12 < 6 else RED,
                                         (70 + i * 4, 70, 160 + i * 4, 160)))
    frames[0].save(os.path.join(FIXTURES, "apng_animated_1.2s.png"),
                   save_all=True, append_images=frames[1:], duration=50,
                   default_image=False)


def make_webm_alpha():
    """2 s VP9 WEBM with alpha, generated from the animated GIF."""
    import subprocess
    out = os.path.join(FIXTURES, "webm_alpha_2s.webm")
    subprocess.run([
        find_ffmpeg(), "-y", "-v", "error", "-i",
        os.path.join(FIXTURES, "gif_animated_2s.gif"),
        "-vf", "format=yuva420p",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-an", "-b:v", "300k",
        "-row-mt", "1", out,
    ], check=True)


def make_mp4():
    import subprocess
    subprocess.run([
        find_ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
        "-i", "testsrc2=size=320x240:rate=24:duration=2.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        os.path.join(FIXTURES, "mp4_opaque_2.5s.mp4"),
    ], check=True)


def make_long_video():
    """6 s MP4 with audio + 60 fps: exercises trim, fps cap, audio strip."""
    import subprocess
    subprocess.run([
        find_ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
        "-i", "testsrc2=size=640x480:rate=60:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", os.path.join(FIXTURES, "mp4_long_6s_60fps_audio.mp4"),
    ], check=True)


def make_malformed():
    with open(os.path.join(FIXTURES, "malformed.bin"), "wb") as f:
        f.write(b"this is not a media file" * 10)
    with open(os.path.join(FIXTURES, "truncated_png.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)


def main() -> int:
    os.makedirs(FIXTURES, exist_ok=True)
    make_static()
    make_gif()
    make_apng()
    make_webm_alpha()
    make_mp4()
    make_long_video()
    make_malformed()
    for name in sorted(os.listdir(FIXTURES)):
        size = os.path.getsize(os.path.join(FIXTURES, name))
        print(f"{name}  {size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
