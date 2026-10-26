#!/usr/bin/env python3
"""Run the extension's JS unit tests in headless Chrome (no Node required).

Starts a local HTTP server for the repository root, loads tests/js/test_runner.html
in headless Chrome, and parses the __TTSTK_RESULTS__ marker from the DOM.
Exits non-zero on any test failure.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if os.path.isfile(path):
            return path
    sys.exit("no Chrome/Edge executable found; edit CHROME_CANDIDATES")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=ROOT)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/tests/js/test_runner.html"
    chrome = find_chrome()
    user_data = os.path.join(os.environ.get("TEMP", "."), "ttstk-js-test-profile")
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        f"--user-data-dir={user_data}",
        "--virtual-time-budget=10000",
        "--dump-dom",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=90, encoding="utf-8", errors="replace")
    finally:
        server.shutdown()

    dom = proc.stdout
    marker = "__TTSTK_RESULTS__"
    idx = dom.find(marker)
    if idx < 0:
        print("TEST RUNNER FAILED: results marker not found in DOM")
        print("--- stderr ---")
        print(proc.stderr[-2000:])
        print("--- stdout tail ---")
        print(dom[-2000:])
        return 2

    raw = dom[idx + len(marker):]
    end = raw.find("</pre>")
    data = json.loads(raw[:end] if end >= 0 else raw)

    print(f"JS tests: {data['pass']} passed, {data['fail']} failed")
    for failure in data["failures"]:
        print(f"  FAIL {failure['name']}: {failure['error']}")
    return 0 if data["fail"] == 0 and data["pass"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
