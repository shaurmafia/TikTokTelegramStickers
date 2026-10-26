#!/usr/bin/env python3
"""Static sanity checks for the extension package (manifest integrity)."""

from __future__ import annotations

import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")


def ext_path(*parts):
    return os.path.join(EXT, *parts)


class TestManifest(unittest.TestCase):
    def setUp(self):
        with open(ext_path("manifest.json"), encoding="utf-8") as f:
            self.manifest = json.load(f)

    def test_manifest_v3_minimum_permissions(self):
        self.assertEqual(self.manifest["manifest_version"], 3)
        perms = set(self.manifest.get("permissions", []))
        self.assertLessEqual(perms, {"storage", "nativeMessaging", "scripting"},
                             "permissions must stay minimal")

    def test_all_referenced_files_exist(self):
        refs = list(self.manifest.get("icons", {}).values())
        refs.append(self.manifest["background"]["service_worker"])
        refs.append(self.manifest["action"]["default_popup"])
        refs.append(self.manifest["options_ui"]["page"])
        for cs in self.manifest.get("content_scripts", []):
            refs.extend(cs.get("js", []))
            refs.extend(cs.get("css", []))
        for ref in refs:
            self.assertTrue(os.path.isfile(ext_path(*ref.split("/"))),
                            f"missing file referenced by manifest: {ref}")

    def test_content_script_world_config(self):
        entries = self.manifest["content_scripts"]
        worlds = [e.get("world", "ISOLATED") for e in entries]
        self.assertIn("MAIN", worlds, "blob bridge must run in MAIN world")
        for entry in entries:
            for pattern in entry["matches"]:
                self.assertRegex(pattern, r"^\*://\*\.tiktok\.com/")

    def test_no_remote_code_sources(self):
        # no <script src="http..."> in any packaged html
        for dirpath, _dirs, files in os.walk(EXT):
            for name in files:
                if name.endswith(".html"):
                    with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                        html = f.read()
                    for m in re.finditer(r'<script[^>]+src="([^"]+)"', html):
                        self.assertFalse(m.group(1).startswith(("http:", "https:")),
                                         f"remote script in {name}: {m.group(1)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
