#!/usr/bin/env python3
"""Register the TikTok Sticker Bridge native messaging host for Chrome/Edge.

Per-user installation (HKCU) — no administrator privileges required.

Usage:
    python install_host.py --extension-id <32-letter extension ID>
                           [--browser chrome|edge|both] [--host-name NAME]

The extension ID is shown on chrome://extensions after loading the unpacked
extension (developer mode). See the repository README for the full walkthrough.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tiktok_sticker_bridge as host  # noqa: E402  (reuse config helpers)

DEFAULT_HOST_NAME = "com.tiktokstickers.bridge"

REGISTRY_PATHS = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
}

BROWSER_EXES = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
}


def write_launcher_bat(host_dir: str, python_exe: str) -> str:
    bat_path = os.path.join(host_dir, "run_host.bat")
    # stdout must stay clean for the protocol: @echo off, @-prefixed command.
    content = (
        "@echo off\r\n"
        f'@"{python_exe}" -u "{os.path.join(host_dir, "tiktok_sticker_bridge.py")}" %*\r\n'
    )
    with open(bat_path, "w", encoding="ascii") as f:
        f.write(content)
    return bat_path


def write_host_manifest(host_dir: str, host_name: str, bat_path: str,
                        extension_id: str) -> str:
    manifest_path = os.path.join(host_dir, f"{host_name}.json")
    manifest = {
        "name": host_name,
        "description": "TikTok Sticker Bridge: saves user-selected TikTok DM "
                       "media to a local folder.",
        "path": bat_path,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest_path


def register(browser: str, host_name: str, manifest_path: str) -> None:
    try:
        import winreg
    except ImportError:
        sys.exit("winreg unavailable: this installer supports Windows only.")
    key_path = rf"{REGISTRY_PATHS[browser]}\{host_name}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, manifest_path)


def browser_found(browser: str) -> bool:
    return any(os.path.isfile(p) for p in BROWSER_EXES[browser])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extension-id", required=True,
                        help="32-character extension ID from chrome://extensions")
    parser.add_argument("--browser", choices=("chrome", "edge", "both"),
                        default="chrome")
    parser.add_argument("--host-name", default=DEFAULT_HOST_NAME)
    args = parser.parse_args()

    ext_id = args.extension_id.strip().lower()
    if not re.fullmatch(r"[a-p]{32}", ext_id):
        parser.error("extension ID must be exactly 32 letters a-p "
                     "(copy it from chrome://extensions)")

    host_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable
    bat_path = write_launcher_bat(host_dir, python_exe)
    manifest_path = write_host_manifest(host_dir, args.host_name, bat_path, ext_id)

    browsers = ["chrome", "edge"] if args.browser == "both" else [args.browser]
    for browser in browsers:
        register(browser, args.host_name, manifest_path)
        state = "found" if browser_found(browser) else "NOT detected on this machine"
        print(f"[ok] registered {browser} (browser install {state})")

    # Keep the host's own origin check in sync with Chrome's allowlist.
    cfg = host.load_config()
    cfg["expected_origin"] = f"chrome-extension://{ext_id}/"
    host.save_config(cfg)

    print(f"[ok] host manifest:  {manifest_path}")
    print(f"[ok] launcher:       {bat_path}")
    print(f"[ok] config:         {host.config_path()} (expected_origin updated)")
    print()
    print("Next steps:")
    print("  1. (Re)start Chrome so it re-reads the registry.")
    print("  2. Open the extension popup -> Options -> 'Choose output folder'")
    print("     or run the connection test from the Options page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
