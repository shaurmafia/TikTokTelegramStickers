#!/usr/bin/env python3
"""End-to-end tests: spawn tiktok_sticker_bridge.py and speak the real
Chrome length-prefixed JSON protocol over stdio pipes."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.join(HERE, "..", "tiktok_sticker_bridge.py")
TEST_ORIGIN = "chrome-extension://abcdefghijklmnop/"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00\x11\x22\x33" * 8
FAKE_SECRET = b"traversal-payload-" + b"A" * 32


class HostProcess:
    """Wrapper that talks the native messaging protocol to a spawned host."""

    def __init__(self, origin: str | None, config_path: str):
        argv = [sys.executable, "-u", HOST, "--config", config_path]
        if origin:
            argv.append(origin)
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def send_raw(self, payload: bytes) -> None:
        self.proc.stdin.write(struct.pack("<I", len(payload)))
        self.proc.stdin.write(payload)
        self.proc.stdin.flush()

    def send(self, obj: dict) -> None:
        self.send_raw(json.dumps(obj).encode("utf-8"))

    def send_text(self, text: str) -> None:
        self.send_raw(text.encode("utf-8"))

    def recv(self, timeout: float = 15.0) -> dict | None:
        # BufferedReader.read(4) blocks until 4 bytes or EOF; a hung host would
        # block the suite, so keep individual payloads small and bounded.
        header = self.proc.stdout.read(4)
        if len(header) < 4:
            return None
        (length,) = struct.unpack("<I", header)
        body = self.proc.stdout.read(length)
        return json.loads(body.decode("utf-8"))

    def request(self, obj: dict, timeout: float = 15.0) -> dict:
        self.send(obj)
        reply = self.recv(timeout)
        assert reply is not None, "host closed stdout before replying"
        return reply

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def make_config(tmp: str, **overrides) -> str:
    cfg = {
        "output_dir": os.path.join(tmp, "out"),
        "max_file_mb": 1,
        "expected_origin": TEST_ORIGIN,
        "duplicate_policy": "skip",
    }
    cfg.update(overrides)
    if cfg["output_dir"]:
        os.makedirs(cfg["output_dir"], exist_ok=True)
    path = os.path.join(tmp, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ttstk-proto-")
        self.cfg = make_config(self.tmp)
        self.host = HostProcess(TEST_ORIGIN, self.cfg)
        self.addCleanup(self.host.close)

    # -- liveness & origin ------------------------------------------------

    def test_health_check_ok(self):
        reply = self.host.request({"type": "health_check"})
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["protocol_version"], 1)
        self.assertTrue(reply["output_dir_configured"])

    def test_unsupported_origin_rejected(self):
        self.host.close()
        self.host = HostProcess("chrome-extension://zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz/",
                                self.cfg)
        reply = self.host.request({"type": "health_check"})
        self.assertEqual(reply["status"], "error")
        self.assertEqual(reply["code"], "UNSUPPORTED_ORIGIN")

    def test_missing_origin_rejected_as_not_installed(self):
        self.host.close()
        empty_cfg = os.path.join(self.tmp, "empty.json")
        with open(empty_cfg, "w", encoding="utf-8") as f:
            json.dump({"expected_origin": ""}, f)
        self.host = HostProcess(None, empty_cfg)
        reply = self.host.request({"type": "get_status"})
        self.assertEqual(reply["code"], "NOT_INSTALLED")

    # -- schema & protocol robustness --------------------------------------

    def test_unsupported_command_rejected(self):
        reply = self.host.request({"type": "delete_everything"})
        self.assertEqual(reply["code"], "INVALID_MESSAGE")

    def test_shell_command_rejected(self):
        reply = self.host.request({"type": "run_shell", "cmd": "format C:"})
        self.assertEqual(reply["code"], "INVALID_MESSAGE")

    def test_unknown_field_rejected(self):
        reply = self.host.request({"type": "health_check", "payload": "x"})
        self.assertEqual(reply["code"], "INVALID_MESSAGE")

    def test_malformed_json_gets_error_reply(self):
        self.host.send_text("this is not json {")
        reply = self.host.recv()
        self.assertEqual(reply["code"], "INVALID_MESSAGE")
        # host must keep operating afterwards
        reply = self.host.request({"type": "health_check"})
        self.assertEqual(reply["status"], "ok")

    def test_get_status_reports_config(self):
        reply = self.host.request({"type": "get_status"})
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["max_file_mb"], 1)
        self.assertEqual(reply["output_dir"], os.path.join(self.tmp, "out"))

    # -- save_original ------------------------------------------------------

    def save(self, data: bytes, filename="sticker.webp", **extra) -> dict:
        msg = {"type": "save_original", "filename": filename,
               "data_base64": b64(data)}
        msg.update(extra)
        return self.host.request(msg)

    def test_fixture_saved_byte_for_byte(self):
        reply = self.save(PNG_MAGIC, "fixture.webp")
        self.assertEqual(reply["status"], "ok")
        self.assertTrue(reply["saved"])
        # content sniffing wins over the suggested .webp name
        self.assertEqual(reply["final_filename"], "fixture.png")
        self.assertEqual(reply["content_type"], "image/png")
        self.assertTrue(reply["verified_content"])
        with open(reply["path"], "rb") as f:
            written = f.read()
        self.assertEqual(written, PNG_MAGIC)          # byte-for-byte
        self.assertEqual(hashlib.sha256(written).hexdigest(), reply["sha256"])

    def test_checksum_mismatch_rejected(self):
        reply = self.save(PNG_MAGIC, sha256="00" * 32)
        self.assertEqual(reply["code"], "CHECKSUM_MISMATCH")

    def test_exact_duplicate_skipped(self):
        first = self.save(PNG_MAGIC, "dup.png")
        self.assertTrue(first["saved"])
        second = self.save(PNG_MAGIC, "dup.png")
        self.assertEqual(second["status"], "ok")
        self.assertTrue(second["duplicate"])
        self.assertFalse(second["saved"])
        self.assertEqual(second["bytes_written"], 0)

    def test_same_name_different_content_suffixed(self):
        a = self.save(PNG_MAGIC, "same.png")
        b = self.save(PNG_MAGIC.replace(b"\x00\x11", b"\x00\x12"), "same.png")
        self.assertEqual(b["status"], "ok")
        self.assertTrue(b["saved"])
        self.assertNotEqual(a["final_filename"], b["final_filename"])
        self.assertEqual(b["final_filename"], "same (1).png")

    def test_duplicate_policy_suffix_writes_anyway(self):
        self.host.close()
        self.host = HostProcess(TEST_ORIGIN,
                                make_config(self.tmp, duplicate_policy="suffix"))
        self.save(PNG_MAGIC, "pol.png")
        second = self.save(PNG_MAGIC, "pol.png")
        self.assertTrue(second["saved"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["final_filename"], "pol (1).png")

    def test_unsafe_filename_rejected(self):
        reply = self.save(FAKE_SECRET, "..\\..\\system32\\payload.bin")
        self.assertIn(reply["code"], ("PATH_NOT_ALLOWED", "INVALID_MESSAGE"))
        # nothing written outside the output dir
        parent = os.path.dirname(self.tmp)
        self.assertNotIn("payload.bin", os.listdir(parent))

    def test_oversized_payload_rejected(self):
        big = PNG_MAGIC + b"\x00" * (1024 * 1024 + 1)   # max_file_mb is 1
        reply = self.save(big, "big.png")
        self.assertEqual(reply["code"], "TOO_LARGE")

    def test_invalid_base64_rejected(self):
        msg = {"type": "save_original", "filename": "x.png",
               "data_base64": "!!!not base64!!!"}
        reply = self.host.request(msg)
        self.assertEqual(reply["code"], "INVALID_FIELD")

    def test_unrecognized_content_saved_as_bin(self):
        payload = b"unknown-format-bytes" * 4
        reply = self.save(payload, "mystery.png")
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["final_filename"], "mystery.bin")
        self.assertFalse(reply["verified_content"])
        self.assertEqual(reply["content_type"], "application/octet-stream")
        with open(reply["path"], "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_no_output_dir_configured(self):
        self.host.close()
        self.host = HostProcess(TEST_ORIGIN,
                                make_config(self.tmp, output_dir=""))
        reply = self.save(PNG_MAGIC, "x.png")
        self.assertEqual(reply["code"], "NO_OUTPUT_DIR")

    def test_animated_gif_classified(self):
        data = b"GIF89a" + b"\x01\x00\x01\x00\x00" + b"\x00\x00\x00" * 4 \
            + b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00" + b"\x3B" + b"x" * 16
        reply = self.save(data, "anim.gif")
        self.assertEqual(reply["final_filename"], "anim.gif")
        self.assertTrue(reply["animated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
