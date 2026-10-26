#!/usr/bin/env python3
"""Unit tests for tiktok_sticker_bridge pure functions (no subprocess)."""

from __future__ import annotations

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tiktok_sticker_bridge as host  # noqa: E402


def gif(animated: bool) -> bytes:
    body = b"GIF89a" + b"\x01\x00\x01\x00\x00" + b"\x00\x00\x00" * 4
    if animated:
        body += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"
    return body + b"\x3B" + b"x" * 32


class TestSanitizeFilename(unittest.TestCase):
    def test_plain_name_kept(self):
        self.assertEqual(host.sanitize_filename("sticker-01.webp"), "sticker-01.webp")

    def test_invalid_windows_chars_replaced(self):
        self.assertEqual(host.sanitize_filename('a<b>:c"d/e\\f|g?h*i'),
                         "a_b__c_d_e_f_g_h_i")

    def test_path_separators_never_survive(self):
        out = host.sanitize_filename("..\\..\\win.ini")
        self.assertNotIn("\\", out)
        self.assertNotIn("/", out)
        self.assertNotIn("..", out)

    def test_control_characters_stripped(self):
        self.assertEqual(host.sanitize_filename("a\x00b\x1fc.webp"), "abc.webp")

    def test_reserved_device_name_prefixed(self):
        self.assertEqual(host.sanitize_filename("CON.webp"), "_CON.webp")
        self.assertEqual(host.sanitize_filename("com1"), "_com1")

    def test_trailing_dots_and_spaces_stripped(self):
        self.assertEqual(host.sanitize_filename("name .webp . "), "name.webp")

    def test_empty_becomes_sticker(self):
        self.assertEqual(host.sanitize_filename(""), "sticker")
        self.assertEqual(host.sanitize_filename("..."), "sticker")

    def test_long_name_truncated(self):
        out = host.sanitize_filename("x" * 500 + ".webp")
        self.assertLessEqual(len(out), len("x" * 150) + len(".webp"))

    def test_non_string_passthrough(self):
        self.assertEqual(host.sanitize_filename(123), "sticker")


class TestCollisionFreePath(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="ttstk-coll-")

    def test_free_name_unchanged(self):
        target, name = host.collision_free_path(self.dir, "a.webp")
        self.assertEqual(name, "a.webp")
        self.assertTrue(target.startswith(self.dir))

    def test_existing_name_gets_suffix(self):
        with open(os.path.join(self.dir, "a.webp"), "wb") as f:
            f.write(b"one")
        _, name1 = host.collision_free_path(self.dir, "a.webp")
        self.assertEqual(name1, "a (1).webp")
        with open(os.path.join(self.dir, name1), "wb") as f:
            f.write(b"two")
        _, name2 = host.collision_free_path(self.dir, "a.webp")
        self.assertEqual(name2, "a (2).webp")

    def test_name_without_extension(self):
        with open(os.path.join(self.dir, "a"), "wb") as f:
            f.write(b"one")
        _, name = host.collision_free_path(self.dir, "a")
        self.assertEqual(name, "a (1)")


class TestResolveTarget(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="ttstk-res-")

    def test_simple_join_allowed(self):
        target = host.resolve_target(self.dir, "ok.webp")
        self.assertTrue(os.path.commonpath([os.path.realpath(self.dir),
                                            os.path.realpath(target)])
                        == os.path.realpath(self.dir))

    def test_separators_rejected(self):
        for bad in ("a/b.webp", "a\\b.webp", "C:evil.webp"):
            with self.assertRaises(ValueError):
                host.resolve_target(self.dir, bad)

    def test_traversal_filename_cannot_escape(self):
        # separators are rejected outright, so no "..\\..\\payload" can pass
        with self.assertRaises(ValueError):
            host.resolve_target(self.dir, "..\\..\\evil.webp")


class TestSniffContent(unittest.TestCase):
    def test_png(self):
        self.assertEqual(host.sniff_content(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20),
                         ("image/png", "png", False))

    def test_gif_static(self):
        self.assertEqual(host.sniff_content(gif(False)), ("image/gif", "gif", False))

    def test_gif_animated(self):
        self.assertEqual(host.sniff_content(gif(True)), ("image/gif", "gif", True))

    def test_jpeg(self):
        self.assertEqual(host.sniff_content(b"\xff\xd8\xff\xe0" + b"\x00" * 20),
                         ("image/jpeg", "jpg", False))

    def test_webp_static(self):
        data = b"RIFF" + struct.pack("<I", 40) + b"WEBP" + b"VP8 " + b"\x00" * 8
        self.assertEqual(host.sniff_content(data), ("image/webp", "webp", False))

    def test_webp_animated_vp8x_flag(self):
        data = (b"RIFF" + struct.pack("<I", 60) + b"WEBP" + b"VP8X"
                + struct.pack("<I", 10) + bytes([0x02]) + b"\x00" * 13)
        self.assertEqual(host.sniff_content(data), ("image/webp", "webp", True))

    def test_mp4(self):
        self.assertEqual(host.sniff_content(b"\x00\x00\x00\x18ftypM4V \x00" + b"\x00" * 20),
                         ("video/mp4", "mp4", True))

    def test_avif(self):
        self.assertEqual(host.sniff_content(b"\x00\x00\x00\x18ftypavif\x00" + b"\x00" * 20),
                         ("image/avif", "avif", False))

    def test_webm(self):
        self.assertEqual(host.sniff_content(b"\x1a\x45\xdf\xa3" + b"\x00" * 20),
                         ("video/webm", "webm", True))

    def test_unknown(self):
        self.assertIsNone(host.sniff_content(b"not a media file at all"))
        self.assertIsNone(host.sniff_content(b"short"))


class TestValidateMessage(unittest.TestCase):
    def test_valid_save(self):
        msg = {"type": "save_original", "filename": "a.webp",
               "data_base64": "AAAA", "sha256": "ab" * 32, "overwrite": False}
        self.assertEqual(host.validate_message(msg), msg)

    def test_unknown_command(self):
        with self.assertRaises(host.ValidationError):
            host.validate_message({"type": "run_shell", "cmd": "dir"})

    def test_unknown_field(self):
        with self.assertRaises(host.ValidationError):
            host.validate_message({"type": "health_check", "extra": 1})

    def test_missing_required(self):
        with self.assertRaises(host.ValidationError):
            host.validate_message({"type": "save_original", "filename": "a"})

    def test_wrong_type(self):
        with self.assertRaises(host.ValidationError):
            host.validate_message({"type": "save_original",
                                   "filename": "a", "data_base64": 5})

    def test_non_object(self):
        with self.assertRaises(host.ValidationError):
            host.validate_message([1, 2, 3])

    def test_bad_sha256(self):
        with self.assertRaises(host.ValidationError):
            host.validate_message({"type": "save_original", "filename": "a",
                                   "data_base64": "AAAA", "sha256": "xyz"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
