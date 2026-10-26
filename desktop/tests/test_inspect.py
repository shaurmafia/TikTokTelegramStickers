"""Inspection tests: classification, measurements, alpha, animation."""

from desktop.core.inspect import (KIND_ANIMATED, KIND_STATIC, KIND_UNSUPPORTED,
                                  KIND_VIDEO, inspect, resolve_profile)


def f(fixtures_dir, name):
    return str(fixtures_dir / name) if hasattr(fixtures_dir, "__truediv__") else \
        __import__("os").path.join(fixtures_dir, name)


class TestClassification:
    def test_static_png(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "png_landscape_700x500.png"))
        assert info.kind == KIND_STATIC
        assert (info.width, info.height) == (700, 500)
        assert info.has_alpha

    def test_jpeg_no_alpha(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "jpeg_opaque_600x600.jpg"))
        assert info.kind == KIND_STATIC
        assert not info.has_alpha

    def test_static_webp(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "webp_static_alpha_500x512.webp"))
        assert info.kind == KIND_STATIC
        assert info.has_alpha

    def test_animated_gif(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "gif_animated_2s.gif"))
        assert info.kind == KIND_ANIMATED
        assert info.frame_count == 40
        assert 1.8 <= info.duration <= 2.2
        assert info.has_alpha

    def test_apng(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "apng_animated_1.2s.png"))
        assert info.kind == KIND_ANIMATED
        assert info.frame_count == 24

    def test_webm_video(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "webm_alpha_2s.webm"))
        assert info.kind == KIND_VIDEO
        assert info.codec == "vp9"
        assert info.has_alpha
        assert info.has_audio is False
        assert 1.5 <= info.duration <= 2.5

    def test_mp4_video(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "mp4_long_6s_60fps_audio.mp4"))
        assert info.kind == KIND_VIDEO
        assert info.has_audio
        assert info.fps > 55
        assert info.duration > 5

    def test_malformed(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "malformed.bin"))
        assert info.kind == KIND_UNSUPPORTED

    def test_truncated_png(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "truncated_png.png"))
        assert info.kind == KIND_UNSUPPORTED
        assert any("cannot decode" in n for n in info.notes)

    def test_missing_file(self, fixtures_dir):
        info = inspect(f(fixtures_dir, "does_not_exist.png"))
        assert info.kind == KIND_UNSUPPORTED


class TestProfileResolution:
    def test_static(self, fixtures_dir):
        assert resolve_profile(inspect(f(fixtures_dir, "png_landscape_700x500.png"))) == "static"

    def test_animated_to_video(self, fixtures_dir):
        assert resolve_profile(inspect(f(fixtures_dir, "gif_animated_2s.gif"))) == "video"

    def test_video(self, fixtures_dir):
        assert resolve_profile(inspect(f(fixtures_dir, "mp4_opaque_2.5s.mp4"))) == "video"

    def test_unsupported(self, fixtures_dir):
        assert resolve_profile(inspect(f(fixtures_dir, "malformed.bin"))) is None
