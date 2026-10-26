"""Static conversion + validation tests."""

import os

from PIL import Image

from desktop.core.static_converter import (StaticConversionError,
                                           convert_static, target_dimensions)
from desktop.core.validate import validate_static

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def out(tmp_path, name):
    return str(tmp_path / name)


def alpha_min(path):
    with Image.open(path) as img:
        if img.mode != "RGBA":
            return 255
        return img.getchannel("A").getextrema()[0]


class TestTargetDimensions:
    def test_landscape(self):
        assert target_dimensions(700, 500) == (512, 366, True, False)

    def test_portrait(self):
        assert target_dimensions(300, 900) == (171, 512, True, False)

    def test_square_exact(self):
        assert target_dimensions(512, 512) == (512, 512, False, False)

    def test_tiny_upscaled(self):
        w, h, resized, up = target_dimensions(64, 64)
        assert (w, h) == (512, 512) and up

    def test_rounding_keeps_512(self):
        w, h, _, _ = target_dimensions(1000, 333)
        assert max(w, h) == 512


class TestStaticConversion:
    def test_landscape_png(self, tmp_path):
        dst = out(tmp_path, "land.webp")
        res = convert_static(os.path.join(FIX, "png_landscape_700x500.png"), dst)
        assert res.format in ("PNG", "WEBP")
        with Image.open(dst) as img:
            assert img.size == (512, 366)
            assert img.mode == "RGBA"
        assert os.path.getsize(dst) <= 512 * 1024
        v = validate_static(dst, expect_alpha=True)
        assert v.ok, [c for c in v.checks if not c.passed]

    def test_portrait(self, tmp_path):
        dst = out(tmp_path, "port.webp")
        convert_static(os.path.join(FIX, "png_portrait_300x900.png"), dst)
        with Image.open(dst) as img:
            assert img.size == (171, 512)
        assert validate_static(dst, expect_alpha=True).ok

    def test_tiny_upscale_warns(self, tmp_path):
        dst = out(tmp_path, "tiny.webp")
        res = convert_static(os.path.join(FIX, "png_tiny_64x64.png"), dst)
        assert any("upscaled" in w for w in res.warnings)
        with Image.open(dst) as img:
            assert img.size == (512, 512)

    def test_alpha_edges_no_dark_fringes(self, tmp_path):
        """The circle hole edge must stay free of dark halos after scaling."""
        dst = out(tmp_path, "edge.webp")
        convert_static(os.path.join(FIX, "png_landscape_700x500.png"), dst)
        with Image.open(dst) as img:
            img = img.convert("RGBA")
            w, h = img.size
            px = img.load()
            # sample pixels just outside the (resized) hole boundary; their
            # RGB must not be black-fringed (alpha ~0 areas excluded)
            fringe_dark = 0
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                x, y = w // 2 + dx, int(h * 0.5) + dy
                r, g, b, a = px[x, y]
                if a > 200 and r + g + b < 60:
                    fringe_dark += 1
            assert fringe_dark == 0

    def test_jpeg_no_alpha_warns(self, tmp_path):
        dst = out(tmp_path, "jpg.webp")
        res = convert_static(os.path.join(FIX, "jpeg_opaque_600x600.jpg"), dst)
        assert any("no alpha" in w for w in res.warnings)
        assert validate_static(dst, expect_alpha=False).ok

    def test_quality_modes_deterministic(self, tmp_path):
        src = os.path.join(FIX, "png_large_2000x2000.png")
        outs = []
        for mode in ("quality_first", "size_first"):
            dst = out(tmp_path, f"{mode}.webp")
            res = convert_static(src, dst, quality_mode=mode)
            outs.append((dst, res.quality))
        # same mode twice -> identical bytes (deterministic settings)
        dst2 = out(tmp_path, "qf2.webp")
        convert_static(src, dst2, quality_mode="quality_first")
        with open(outs[0][0], "rb") as a, open(dst2, "rb") as b:
            assert a.read() == b.read()
        for path, _ in outs:
            assert os.path.getsize(path) <= 512 * 1024

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        dst = out(tmp_path, "atomic.webp")
        convert_static(os.path.join(FIX, "png_tiny_64x64.png"), dst)
        assert not os.path.exists(dst + ".tmp")

    def test_unicode_filename(self, tmp_path):
        dst = out(tmp_path, "стикер #1 — тест.webp")
        res = convert_static(os.path.join(FIX, "png_tiny_64x64.png"), dst)
        assert os.path.exists(res.output_path)


class TestStaticValidation:
    def test_rejects_oversize_fake(self, tmp_path):
        p = tmp_path / "fake.webp"
        p.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100)
        v = validate_static(str(p))
        assert not v.ok

    def test_rejects_wrong_dimensions(self, tmp_path):
        p = tmp_path / "bad.png"
        Image.new("RGBA", (400, 400), (255, 0, 0, 255)).save(p)
        v = validate_static(str(p))
        assert not v.ok
        assert any(c.name == "dimensions" and not c.passed for c in v.checks)

    def test_accepts_valid(self, tmp_path):
        p = tmp_path / "ok.webp"
        Image.new("RGBA", (512, 300), (10, 20, 30, 200)).save(
            p, "WEBP", lossless=True)
        assert validate_static(str(p), expect_alpha=True).ok
