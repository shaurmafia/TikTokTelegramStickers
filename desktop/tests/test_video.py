"""Video conversion + validation tests (VP9 WEBM, real FFmpeg runs)."""

import os

from desktop.core.validate import validate_video

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class TestVideoConversion:
    def test_gif_to_webm_alpha(self, tmp_path):
        from desktop.core.convert import run_conversion
        from desktop.core.profiles import ConversionRequest
        from desktop.core.file_manager import Workspace
        ws = Workspace(str(tmp_path / "ws"))
        req = ConversionRequest(
            source=os.path.join(FIX, "gif_animated_2s.gif"), profile="video",
            quality_mode="balanced",
            output_dir=ws.output_dir, temp_dir=ws.temp_dir,
            originals_dir=ws.originals_dir, failed_dir=ws.failed_dir,
            reports_dir=ws.reports_dir)
        report = run_conversion(req)
        assert report.status == "ok", (report.error, report.warnings)
        assert report.telegram_ready
        v = validate_video(report.output_path, expect_alpha=True)
        assert v.ok, [c for c in v.checks if not c.passed]

    def test_mp4_no_audio_after_convert(self, tmp_path):
        from desktop.core.convert import run_conversion
        from desktop.core.profiles import ConversionRequest
        from desktop.core.file_manager import Workspace
        ws = Workspace(str(tmp_path / "ws"))
        req = ConversionRequest(
            source=os.path.join(FIX, "mp4_opaque_2.5s.mp4"), profile="video",
            quality_mode="size_first",
            output_dir=ws.output_dir, temp_dir=ws.temp_dir,
            originals_dir=ws.originals_dir, failed_dir=ws.failed_dir,
            reports_dir=ws.reports_dir)
        report = run_conversion(req)
        assert report.status == "ok", (report.error, report.warnings)
        v = validate_video(report.output_path, expect_alpha=False)
        assert v.ok, [c for c in v.checks if not c.passed]

    def test_long_video_trimmed_and_fps_capped(self, tmp_path):
        """6 s / 60 fps / audio source: trim to 3 s, cap 30 fps, strip audio,
        with explicit warnings (never silent)."""
        from desktop.core.convert import run_conversion
        from desktop.core.profiles import ConversionRequest
        from desktop.core.file_manager import Workspace
        ws = Workspace(str(tmp_path / "ws"))
        req = ConversionRequest(
            source=os.path.join(FIX, "mp4_long_6s_60fps_audio.mp4"), profile="video",
            quality_mode="size_first", duration_policy="trim_first",
            output_dir=ws.output_dir, temp_dir=ws.temp_dir,
            originals_dir=ws.originals_dir, failed_dir=ws.failed_dir,
            reports_dir=ws.reports_dir)
        report = run_conversion(req)
        assert report.status == "ok", (report.error, report.warnings)
        assert any("trimmed" in w for w in report.warnings)
        assert any("fps" in w for w in report.warnings)
        v = validate_video(report.output_path, expect_alpha=False)
        assert v.ok, [c for c in v.checks if not c.passed]

    def test_webm_reencode_alpha_survives(self, tmp_path):
        """WEBM source with alpha -> new WEBM must still decode transparent."""
        from desktop.core.convert import run_conversion
        from desktop.core.profiles import ConversionRequest
        from desktop.core.file_manager import Workspace
        ws = Workspace(str(tmp_path / "ws"))
        req = ConversionRequest(
            source=os.path.join(FIX, "webm_alpha_2s.webm"), profile="video",
            quality_mode="balanced",
            output_dir=ws.output_dir, temp_dir=ws.temp_dir,
            originals_dir=ws.originals_dir, failed_dir=ws.failed_dir,
            reports_dir=ws.reports_dir)
        report = run_conversion(req)
        assert report.status == "ok", (report.error, report.warnings)
        v = validate_video(report.output_path, expect_alpha=True)
        assert v.ok, [c for c in v.checks if not c.passed]

    def test_output_never_exceeds_limit(self, tmp_path):
        from desktop.core.convert import run_conversion
        from desktop.core.profiles import ConversionRequest
        from desktop.core.file_manager import Workspace
        ws = Workspace(str(tmp_path / "ws"))
        req = ConversionRequest(
            source=os.path.join(FIX, "gif_animated_2s.gif"), profile="video",
            quality_mode="quality_first",
            output_dir=ws.output_dir, temp_dir=ws.temp_dir,
            originals_dir=ws.originals_dir, failed_dir=ws.failed_dir,
            reports_dir=ws.reports_dir)
        report = run_conversion(req)
        assert os.path.getsize(report.output_path) <= 256 * 1024
        assert len(report.attempt_notes) >= 1


class TestFilterChain:
    def test_landscape_scale(self):
        from desktop.core.video_converter import build_filter_chain
        chain, fps, dur, warns = build_filter_chain(700, 500, 24.0, 2.0, "trim_first")
        assert "512" in chain and "-2" in chain
        assert fps == 24.0 and not warns

    def test_fps_cap_warns(self):
        from desktop.core.video_converter import build_filter_chain
        chain, fps, dur, warns = build_filter_chain(400, 400, 60.0, 2.0, "trim_first")
        assert "fps=30" in chain and fps == 30 and warns

    def test_trim_warns(self):
        from desktop.core.video_converter import build_filter_chain
        chain, fps, dur, warns = build_filter_chain(400, 400, 24.0, 6.0, "trim_first")
        assert "trim=duration=3" in chain and warns

    def test_speed_policy(self):
        from desktop.core.video_converter import build_filter_chain
        chain, fps, dur, warns = build_filter_chain(400, 400, 24.0, 6.0, "speed_up")
        assert "setpts" in chain and warns
