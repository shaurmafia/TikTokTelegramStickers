#!/usr/bin/env python3
"""Remove the TikTok Sticker Bridge native messaging host registration.

Usage:
    python uninstall_host.py [--browser chrome|edge|both] [--host-name NAME]
                             [--purge]

Without --purge, only the registry keys are removed and downloaded media is
untouched. With --purge, the launcher .bat, host manifest JSON, and the host
config directory are deleted as well. Saved sticker files in the chosen
output folder are NEVER deleted by this script.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tiktok_sticker_bridge as host  # noqa: E402

REGISTRY_ROOTS = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
}


def unregister(browser: str, host_name: str) -> bool:
    import winreg
    key_path = rf"{REGISTRY_ROOTS[browser]}\{host_name}"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        return True
    except FileNotFoundError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", choices=("chrome", "edge", "both"),
                        default="chrome")
    parser.add_argument("--host-name", default="com.tiktokstickers.bridge")
    parser.add_argument("--purge", action="store_true",
                        help="also delete launcher, host manifest, and host config")
    args = parser.parse_args()

    browsers = ["chrome", "edge"] if args.browser == "both" else [args.browser]
    for browser in browsers:
        removed = unregister(browser, args.host_name)
        print(f"[{'ok' if removed else 'skip'}] {browser}: "
              f"{'removed' if removed else 'was not registered'}")

    if args.purge:
        host_dir = os.path.dirname(os.path.abspath(__file__))
        for name in ("run_host.bat", f"{args.host_name}.json"):
            p = os.path.join(host_dir, name)
            if os.path.isfile(p):
                os.unlink(p)
                print(f"[ok] deleted {p}")
        cfg_dir = host.config_dir()
        if os.path.isdir(cfg_dir):
            shutil.rmtree(cfg_dir)
            print(f"[ok] deleted {cfg_dir}")
        print("Saved media in your chosen output folder was not touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
