#!/usr/bin/env python3
"""Print the extension ID Chrome assigns to this unpacked extension.

For unpacked extensions Chrome derives the ID from the absolute path
(SHA-256 of the UTF-16-LE path, hex digits mapped to a-p). Verify the printed
value against chrome://extensions after loading the extension; if Chrome shows
a different ID, pass the real one to install_host.bat instead.
"""

import hashlib
import os
import sys

EXT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "extension"))


def unpacked_id(path: str) -> str:
    digest = hashlib.sha256(os.path.normpath(path).encode("utf-16-le")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else EXT_DIR
    print(unpacked_id(path))
