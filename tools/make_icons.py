#!/usr/bin/env python3
"""Generate extension icons (16/32/48/128 px) with a pure-Python PNG writer.

Design: dark rounded square, TikTok-style cyan/red accent bar, white
download-arrow-into-tray glyph. No external dependencies.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "extension", "assets", "icons")

BG = (24, 24, 32, 255)          # dark slate
BG_EDGE = (38, 38, 52, 255)
CYAN = (37, 244, 238, 255)
RED = (254, 44, 85, 255)
WHITE = (245, 245, 250, 255)
CLEAR = (0, 0, 0, 0)


def clamp(v):
    return max(0, min(255, v))


def make_icon(size: int) -> list[list[tuple]]:
    px = [[CLEAR] * size for _ in range(size)]
    radius = max(2, size // 5)
    edge = max(1, size // 16)

    def in_rounded(x, y):
        r = radius
        w = size
        dx = min(x, w - 1 - x)
        dy = min(y, w - 1 - y)
        if dx >= r or dy >= r:
            return True
        return (r - dx) ** 2 + (r - dy) ** 2 <= r * r

    for y in range(size):
        for x in range(size):
            if not in_rounded(x, y):
                continue
            # subtle inner highlight near top-left edge
            px[x][y] = BG_EDGE if (x < edge or y < edge) else BG

    # accent bar along the left edge (cyan above, red below)
    bar_w = max(1, size // 10)
    for y in range(size):
        for x in range(0, bar_w):
            if px[x][y] != CLEAR:
                px[x][y] = CYAN if y < size // 2 else RED

    # glyph: arrow down into a tray, centered
    cx = size // 2
    top = int(size * 0.22)
    bot = int(size * 0.62)
    shaft_w = max(1, size // 12)
    head_w = max(2, size // 4)

    def put(x, y, color):
        if 0 <= x < size and 0 <= y < size and px[x][y] != CLEAR:
            px[x][y] = color

    for y in range(top, bot):
        for x in range(cx - shaft_w // 2, cx + shaft_w // 2 + 1):
            put(x, y, WHITE)
    head_h = max(2, size // 8)
    for i in range(head_h):
        span = head_w * (i + 1) // head_h
        for x in range(cx - span, cx + span + 1):
            put(x, bot + i, WHITE)
    tray_y0 = bot + head_h + max(1, size // 32)
    tray_t = max(1, size // 24)
    tray_half = int(size * 0.28)
    for i in range(tray_t):
        for x in range(cx - tray_half, cx + tray_half + 1):
            put(x, tray_y0 + i, WHITE)
    for i in range(max(1, size // 14)):
        for yy in (tray_y0, tray_y0 + tray_t - 1):
            put(cx - tray_half, yy + i, WHITE)
            put(cx + tray_half, yy + i, WHITE)
    return px


def write_png(path: str, px: list[list[tuple]]) -> None:
    h = len(px)
    w = len(px[0])
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            raw += bytes(px[x][y])

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    for size in (16, 32, 48, 128):
        path = os.path.join(OUT_DIR, f"icon{size}.png")
        write_png(path, make_icon(size))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
