#!/usr/bin/env python3
"""Smoke-test the full native-host launch chain on Windows:

install (HKCU registry + manifest + .bat launcher) -> run run_host.bat exactly
the way Chrome would -> health_check -> save_original -> byte-for-byte check.

Verifies the pieces that Chrome-side automation cannot reach on branded
Chrome builds (which ignore --load-extension).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "native_host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import compute_extension_id  # noqa: E402
import tiktok_sticker_bridge as host  # noqa: E402

FIXTURE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSnc"
    "AAAAEUlEQVR42mM4o+SCFTEMLQkABopMgbu286wAAAAASUVORK5CYII=")
EXT_ID = compute_extension_id.unpacked_id(os.path.join(ROOT, "extension"))
ORIGIN = f"chrome-extension://{EXT_ID}/"


def read_message(pipe):
    header = pipe.read(4)
    assert len(header) == 4, "host closed early"
    (n,) = struct.unpack("<I", header)
    return json.loads(pipe.read(n).decode("utf-8"))


def send_message(pipe, obj):
    data = json.dumps(obj).encode("utf-8")
    pipe.write(struct.pack("<I", len(data)))
    pipe.write(data)
    pipe.flush()


def main() -> int:
    # 1. install for the computed ID, configure an output dir
    subprocess.run([sys.executable, os.path.join(ROOT, "native_host",
                     "install_host.py"), "--extension-id", EXT_ID],
                   check=True, capture_output=True)
    out_dir = tempfile.mkdtemp(prefix="ttstk-smoke-")
    cfg = host.load_config()
    cfg["output_dir"] = out_dir
    host.save_config(cfg)
    print(f"[ok] installed host for {EXT_ID}; output dir {out_dir}")

    # 2. launch via the .bat exactly as Chrome does
    bat = os.path.join(ROOT, "native_host", "run_host.bat")
    proc = subprocess.Popen(["cmd", "/c", bat, ORIGIN],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)

    # 3. protocol checks
    send_message(proc.stdin, {"type": "health_check"})
    reply = read_message(proc.stdout)
    assert reply["status"] == "ok", reply
    print(f"[ok] run_host.bat health_check: v{reply['version']}")

    send_message(proc.stdin, {
        "type": "save_original", "filename": "smoke-fixture.png",
        "data_base64": base64.b64encode(FIXTURE).decode(),
        "sha256": hashlib.sha256(FIXTURE).hexdigest(),
    })
    reply = read_message(proc.stdout)
    assert reply["status"] == "ok", reply
    with open(reply["path"], "rb") as f:
        assert f.read() == FIXTURE, "bytes differ"
    assert reply["final_filename"] == "smoke-fixture.png"
    print(f"[ok] save_original via run_host.bat: {reply['path']} "
          f"(byte-for-byte verified)")

    proc.stdin.close()
    proc.wait(timeout=10)
    print("SMOKE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
