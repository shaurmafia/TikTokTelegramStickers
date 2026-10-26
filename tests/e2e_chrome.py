#!/usr/bin/env python3
"""End-to-end test: real Chrome + extension + native messaging host.

1. Launches Chrome with --load-extension (CDP remote debugging).
2. Reads the REAL unpacked extension ID from the DevTools target list.
3. Installs the native host for that ID and configures an output dir.
4. Evaluates in the extension service worker: health_check and a
   save_original fixture; verifies the written file byte-for-byte.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_DIR = os.path.join(ROOT, "extension")
sys.path.insert(0, os.path.join(ROOT, "native_host"))
sys.path.insert(0, os.path.join(ROOT, "native_host", "tests"))

FIXTURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSnc"
    "AAAAEUlEQVR42mM4o+SCFTEMLQkABopMgbu286wAAAAASUVORK5CYII=")
FIXTURE_SHA = hashlib.sha256(FIXTURE_PNG).hexdigest()
HOST_NAME = "com.tiktokstickers.bridge"


# ---------------- minimal CDP-over-WebSocket client (stdlib) ----------------

class CDP:
    def __init__(self, ws_url: str):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", ws_url)
        self.sock = socket.create_connection((m.group(1), int(m.group(2))),
                                             timeout=30)
        self.path = m.group(3)
        self._handshake()
        self._buf = b""
        self._next_id = 0

    def _handshake(self):
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        req = (f"GET {self.path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.sock.recv(4096)
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket upgrade failed: " + resp[:200].decode())

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("ws closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_frame(self) -> tuple[int, bytes]:
        head = self._recv_exact(2)
        opcode = head[0] & 0x0F
        length = head[1] & 0x7F
        if length == 126:
            length = int.from_bytes(self._recv_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._recv_exact(8), "big")
        return opcode, self._recv_exact(length)

    def _send_frame(self, opcode: int, payload: bytes):
        mask = secrets.token_bytes(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        if length < 126:
            head = bytes([0x80 | opcode, 0x80 | length])
        elif length < 65536:
            head = bytes([0x80 | opcode, 0x80 | 126]) + length.to_bytes(2, "big")
        else:
            head = bytes([0x80 | opcode, 0x80 | 127]) + length.to_bytes(8, "big")
        self.sock.sendall(head + mask + masked)

    def call(self, method: str, params: dict | None = None,
             session: str | None = None, timeout: float = 30) -> dict:
        self._next_id += 1
        mid = self._next_id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self._send_frame(1, json.dumps(msg).encode())
        deadline = time.time() + timeout
        fragments = []
        while time.time() < deadline:
            opcode, payload = self._read_frame()
            if opcode == 1:
                data = json.loads(payload.decode("utf-8"))
                if data.get("id") == mid:
                    if "error" in data:
                        raise RuntimeError(f"CDP error: {data['error']}")
                    return data.get("result", {})
            elif opcode == 0:
                fragments.append(payload)
            elif opcode == 9:
                self._send_frame(10, payload)
            elif opcode == 8:
                raise ConnectionError("ws closed by peer")
        raise TimeoutError(f"CDP call timed out: {method}")


# ---------------- helpers ----------------

def start_chrome(user_data: str) -> tuple[subprocess.Popen, str]:
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([
        chrome, "--headless=new", "--disable-gpu", "--no-first-run",
        "--disable-features=RenderDocument", "--remote-debugging-port=0",
        f"--user-data-dir={user_data}", f"--load-extension={EXT_DIR}",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    ws_url = None
    while time.time() < deadline:
        line = proc.stderr.readline().decode(errors="replace")
        if "DevTools listening on" in line:
            ws_url = line.split("DevTools listening on")[1].strip()
            break
    if not ws_url:
        proc.kill()
        raise RuntimeError("DevTools endpoint not found")
    return proc, ws_url


def find_extension_sw(port: int, timeout: float = 25) -> tuple[str, str]:
    """Return (extension_id, target_id) of the service worker target."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list",
                                        timeout=5) as r:
                targets = json.loads(r.read().decode())
        except Exception:
            targets = []
        for t in targets:
            url = t.get("url", "")
            if (t.get("type") == "service_worker"
                    and "chrome-extension://" in url
                    and "background/service_worker.js" in url):
                ext_id = url.split("chrome-extension://")[1].split("/")[0]
                return ext_id, t["id"]
        time.sleep(0.5)
    raise RuntimeError("extension service worker target not found")


def install_host(ext_id: str, out_dir: str) -> None:
    import tiktok_sticker_bridge as host
    import install_host as installer
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "native_host", "install_host.py"),
         "--extension-id", ext_id, "--browser", "chrome"],
        check=True, capture_output=True)
    cfg = host.load_config()
    cfg["output_dir"] = out_dir
    host.save_config(cfg)


def evaluate(cdp: CDP, session: str, expression: str) -> dict:
    res = cdp.call("Runtime.evaluate", {
        "expression": expression, "awaitPromise": True, "returnByValue": True,
    }, session=session)
    return res.get("result", {}).get("value")


def host_call_js(payload: str) -> str:
    return (f"new Promise(res => chrome.runtime.sendNativeMessage("
            f"'{HOST_NAME}', {payload}, r => {{"
            f"const e = chrome.runtime.lastError;"
            f"res(e ? {{status:'error', code:'LASTERROR', message:e.message}} : r);"
            f"}}))")


def run_once(attempt: int) -> bool:
    user_data = tempfile.mkdtemp(prefix="ttstk-e2e-")
    out_dir = tempfile.mkdtemp(prefix="ttstk-e2e-out-")
    proc, ws_url = start_chrome(user_data)
    cdp = None
    try:
        port = int(re.search(r":(\d+)/", ws_url).group(1))
        ext_id, target_id = find_extension_sw(port)
        print(f"[ok] extension loaded, real ID: {ext_id}")
        install_host(ext_id, out_dir)
        print("[ok] native host installed for that ID")

        cdp = CDP(ws_url)
        session = cdp.call("Target.attachToTarget",
                           {"targetId": target_id, "flatten": True})["sessionId"]

        ver = evaluate(cdp, session, "chrome.runtime.getManifest().version")
        print(f"[ok] service worker reachable, manifest v{ver}")

        health = evaluate(cdp, session, host_call_js("{type:'health_check'}"))
        if health.get("status") != "ok":
            print(f"[fail] health_check: {health}")
            return False
        print(f"[ok] health_check via Chrome: v{health['version']}, "
              f"output_dir_configured={health['output_dir_configured']}")

        msg = json.dumps({"type": "save_original",
                          "filename": "e2e-fixture.png",
                          "data_base64": base64.b64encode(FIXTURE_PNG).decode(),
                          "media_type": "image/png", "sha256": FIXTURE_SHA,
                          "overwrite": False})
        reply = evaluate(cdp, session, host_call_js(msg))
        if reply.get("status") != "ok":
            print(f"[fail] save_original: {reply}")
            return False
        with open(reply["path"], "rb") as f:
            written = f.read()
        assert written == FIXTURE_PNG, "bytes differ!"
        assert reply["bytes_written"] == len(FIXTURE_PNG)
        assert reply["final_filename"] == "e2e-fixture.png"
        print(f"[ok] save_original: {reply['path']} "
              f"({reply['bytes_written']} bytes, byte-for-byte verified)")
        return True
    finally:
        if cdp:
            try:
                cdp.sock.close()
            except OSError:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    for attempt in (1, 2):
        try:
            if run_once(attempt):
                print("E2E: PASS")
                return 0
            return 1
        except Exception as exc:
            print(f"[attempt {attempt}] {type(exc).__name__}: {exc}")
            if attempt == 2:
                print("E2E: FAIL")
                return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
