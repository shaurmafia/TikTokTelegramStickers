#!/usr/bin/env python3
"""TikTok Sticker Bridge — Chrome Native Messaging host (Windows, Phase 1).

Speaks Chrome's length-prefixed JSON protocol on stdin/stdout and performs a
small, strictly validated command surface on the local filesystem:

    health_check          -> liveness + version info
    get_status            -> current configuration
    choose_output_folder  -> native folder picker (tkinter), stores the result
    save_original         -> writes user-selected media bytes into the
                             configured output directory

Security model
--------------
* Chrome launches this process with the calling extension origin as argv[1].
  Every command is rejected unless it matches ``expected_origin`` in the host
  config file written by the installer (defense in depth on top of Chrome's
  own ``allowed_origins`` enforcement).
* Every message is validated against a strict per-command schema; unknown
  commands, unknown fields, and wrong types are rejected.
* File writes are confined to the configured output directory. Filenames are
  sanitized, path separators and traversal are rejected, and the final path
  is verified to resolve inside the output directory.
* The extension can never ask for shell commands, subprocesses, or arbitrary
  paths. Nothing here executes input.
* Diagnostics go to stderr only; stdout carries protocol messages exclusively.
* Writes are atomic (temp file + os.replace); duplicates are detected by
  SHA-256; file extensions are derived from sniffed magic bytes, not from the
  requested filename.

Runs on Python 3.9+ using the standard library only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import time
import unicodedata

PROTOCOL_VERSION = 1
HOST_VERSION = "1.0.0"

MAX_MESSAGE_IN_BYTES = 140_000_000      # defensive cap on inbound frame size
MAX_FILE_MB_DEFAULT = 25
MAX_FILE_MB_LIMIT = 100
MAX_FILENAME_LEN = 150
PROCESSING_TIMEOUT_S = 120              # per non-interactive command

WINDOWS_INVALID_CHARS = '<>:"/\\|?*'
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# ---------------------------------------------------------------------------
# Logging (stderr only)
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    sys.stderr.write(f"[ttstk-bridge {time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def config_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "TikTokStickersBridge")


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def default_config() -> dict:
    return {
        "output_dir": "",
        "max_file_mb": MAX_FILE_MB_DEFAULT,
        "expected_origin": "",
        "duplicate_policy": "skip",  # "skip" | "suffix"
    }


def load_config(path: str | None = None) -> dict:
    cfg = default_config()
    p = path or config_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in cfg})
    except FileNotFoundError:
        pass
    except Exception as exc:  # corrupted config must not crash the host
        log(f"config unreadable ({exc!r}); using defaults")
    if not isinstance(cfg.get("max_file_mb"), int) or cfg["max_file_mb"] < 1:
        cfg["max_file_mb"] = MAX_FILE_MB_DEFAULT
    cfg["max_file_mb"] = min(cfg["max_file_mb"], MAX_FILE_MB_LIMIT)
    if cfg.get("duplicate_policy") not in ("skip", "suffix"):
        cfg["duplicate_policy"] = "skip"
    return cfg


def save_config(cfg: dict, path: str | None = None) -> None:
    p = path or config_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Filename handling
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Return a safe, flat filename derived from untrusted input."""
    if not isinstance(name, str):
        return "sticker"
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if ord(ch) >= 32 and unicodedata.category(ch)[0] != "C")
    for ch in WINDOWS_INVALID_CHARS:
        name = name.replace(ch, "_")
    name = re.sub(r"\.{2,}", "_", name)   # no ".." runs, even mid-name
    name = name.strip(" .")
    base = os.path.basename(name)
    stem, dot, ext = base.rpartition(".")
    stem = stem if dot else base
    ext = ext if dot else ""
    stem = stem[:MAX_FILENAME_LEN].strip(" ._") or "sticker"
    if stem.upper() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    return f"{stem}.{ext}" if ext else stem


def split_name_ext(name: str) -> tuple[str, str]:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return name, ""
    return stem or "sticker", ext


def collision_free_path(directory: str, filename: str) -> tuple[str, str]:
    """Find a non-existing filename in *directory*, appending ' (n)' if needed."""
    stem, ext = split_name_ext(filename)
    candidate = filename
    n = 1
    while True:
        target = os.path.join(directory, candidate)
        if not os.path.lexists(target):
            return target, candidate
        candidate = f"{stem} ({n}){('.' + ext) if ext else ''}"
        n += 1
        if n > 999:
            candidate = f"{stem} ({int(time.time())}){('.' + ext) if ext else ''}"
            return os.path.join(directory, candidate), candidate


def resolve_target(directory: str, filename: str) -> str:
    """Join and verify the destination stays inside *directory* (no traversal)."""
    if any(ch in filename for ch in ("/", "\\", ":")):
        raise ValueError("filename must not contain path separators")
    target = os.path.join(directory, filename)
    root = os.path.realpath(directory)
    resolved = os.path.realpath(target)
    if os.path.commonpath([root, resolved]) != root:
        raise ValueError("resolved path escapes the output directory")
    return resolved


# ---------------------------------------------------------------------------
# Content sniffing (magic bytes -> (content_type, extension, animated))
# ---------------------------------------------------------------------------

def sniff_content(data: bytes) -> tuple[str, str, bool] | None:
    """Identify media by magic bytes.

    Returns (mime_type, extension, animated) or None if unrecognized.
    Extension omits the leading dot.
    """
    if len(data) < 12:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png", False
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        animated = b"NETSCAPE2.0" in data[:4096]
        return "image/gif", "gif", animated
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg", False
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X" and len(data) > 20 and (data[20] & 0x02):
            return "image/webp", "webp", True
        return "image/webp", "webp", False
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif", "avif", brand == b"avis"
        return "video/mp4", "mp4", True
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm", "webm", True
    return None


# ---------------------------------------------------------------------------
# Message validation
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    pass


SCHEMAS: dict[str, dict] = {
    "health_check": {},
    "get_status": {},
    "choose_output_folder": {},
    "save_original": {
        "filename": (str, True),
        "data_base64": (str, True),
        "media_type": (str, False),
        "sha256": (str, False),
        "overwrite": (bool, False),
    },
}


def validate_message(msg: object) -> dict:
    if not isinstance(msg, dict):
        raise ValidationError("message must be a JSON object")
    cmd = msg.get("type")
    if not isinstance(cmd, str) or cmd not in SCHEMAS:
        raise ValidationError(f"unsupported command: {cmd!r}")
    schema = SCHEMAS[cmd]
    for key, value in msg.items():
        if key == "type":
            continue
        if key not in schema:
            raise ValidationError(f"unexpected field {key!r} for {cmd}")
        expected = schema[key][0]
        if not isinstance(value, expected):
            raise ValidationError(
                f"field {key!r} must be {expected.__name__}"
            )
    for key, (_, required) in schema.items():
        if required and key not in msg:
            raise ValidationError(f"missing required field {key!r} for {cmd}")
    if cmd == "save_original":
        if not msg["filename"].strip():
            raise ValidationError("filename must not be empty")
        if len(msg["data_base64"]) == 0:
            raise ValidationError("data_base64 must not be empty")
        sha = msg.get("sha256")
        if sha is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            raise ValidationError("sha256 must be 64 hex characters")
    return msg


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def err(code: str, message: str) -> dict:
    return {"status": "error", "code": code, "message": message}


def check_origin(cfg: dict, origin: str | None) -> str | None:
    expected = cfg.get("expected_origin")
    if not expected:
        return "NOT_INSTALLED"
    # Chrome passes "chrome-extension://<id>/"; tolerate a missing trailing
    # slash on either side so normalization can't cause false rejections.
    if origin is None or origin.rstrip("/") != expected.rstrip("/"):
        return "UNSUPPORTED_ORIGIN"
    return None


def cmd_health_check(cfg: dict, origin: str | None) -> dict:
    blocked = check_origin(cfg, origin)
    if blocked:
        return err(blocked, "origin not allowed by host configuration")
    return {
        "status": "ok",
        "version": HOST_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "output_dir_configured": bool(cfg.get("output_dir")),
    }


def cmd_get_status(cfg: dict, origin: str | None) -> dict:
    blocked = check_origin(cfg, origin)
    if blocked:
        return err(blocked, "origin not allowed by host configuration")
    return {
        "status": "ok",
        "version": HOST_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "output_dir": cfg.get("output_dir", ""),
        "max_file_mb": cfg["max_file_mb"],
        "duplicate_policy": cfg["duplicate_policy"],
        "config_path": config_path(),
    }


def cmd_choose_output_folder(cfg: dict, origin: str | None) -> dict:
    blocked = check_origin(cfg, origin)
    if blocked:
        return err(blocked, "origin not allowed by host configuration")
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        return err("DIALOG_UNAVAILABLE",
                   f"tkinter unavailable on this Python install: {exc}")
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askdirectory(
            title="Choose folder for saved stickers",
            initialdir=cfg.get("output_dir") or os.path.expanduser("~"),
        )
    finally:
        root.destroy()
    if not chosen:
        return {"status": "ok", "cancelled": True}
    chosen = os.path.realpath(chosen)
    if not os.path.isdir(chosen):
        return err("INVALID_FOLDER", "selected path is not a directory")
    cfg["output_dir"] = chosen
    save_config(cfg)
    log(f"output dir set to {chosen}")
    return {"status": "ok", "output_dir": chosen}


def cmd_save_original(cfg: dict, origin: str | None, msg: dict) -> dict:
    blocked = check_origin(cfg, origin)
    if blocked:
        return err(blocked, "origin not allowed by host configuration")
    output_dir = cfg.get("output_dir")
    if not output_dir or not os.path.isdir(output_dir):
        return err("NO_OUTPUT_DIR",
                   "no output folder configured; run choose_output_folder first")

    max_bytes = cfg["max_file_mb"] * 1024 * 1024
    try:
        raw = base64.b64decode(msg["data_base64"], validate=True)
    except (binascii.Error, ValueError):
        return err("INVALID_FIELD", "data_base64 is not valid base64")
    if not raw:
        return err("INVALID_FIELD", "decoded payload is empty")
    if len(raw) > max_bytes:
        return err("TOO_LARGE",
                   f"payload is {len(raw)} bytes; limit is {max_bytes} bytes")

    sha_given = (msg.get("sha256") or "").lower()
    sha_actual = hashlib.sha256(raw).hexdigest()
    if sha_given and sha_given != sha_actual:
        return err("CHECKSUM_MISMATCH",
                   "payload does not match the declared sha256")

    sniffed = sniff_content(raw)
    if sniffed:
        content_type, true_ext, animated = sniffed
        verified_content = True
    else:
        content_type, true_ext, animated = "application/octet-stream", "bin", False
        verified_content = False

    raw_name = msg["filename"]
    if any(ch in raw_name for ch in ("/", "\\", ":")) or ".." in raw_name:
        return err("PATH_NOT_ALLOWED",
                   "filename must be a bare name without path components")
    filename = sanitize_filename(raw_name)
    stem, _ = split_name_ext(filename)
    filename = f"{stem}.{true_ext}"
    try:
        target = resolve_target(output_dir, filename)
    except ValueError as exc:
        return err("PATH_NOT_ALLOWED", str(exc))

    overwrite = bool(msg.get("overwrite"))
    duplicate = False
    skipped = False
    if os.path.lexists(target) and not overwrite:
        with open(target, "rb") as f:
            existing_sha = hashlib.sha256(f.read()).hexdigest()
        if existing_sha == sha_actual:
            duplicate = True
            if cfg["duplicate_policy"] == "skip":
                skipped = True
                final_path, final_name = target, os.path.basename(target)
            else:
                final_path, final_name = collision_free_path(output_dir, filename)
        else:
            final_path, final_name = collision_free_path(output_dir, filename)
    else:
        final_path, final_name = target, filename

    bytes_written = 0
    if not skipped:
        fd, tmp_path = tempfile.mkstemp(prefix=".ttstk-", dir=output_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, final_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        bytes_written = len(raw)

    log(f"saved {final_name} ({content_type}, animated={animated}, "
        f"{bytes_written} bytes) -> {final_path}")
    return {
        "status": "ok",
        "saved": not skipped,
        "duplicate": duplicate,
        "path": final_path,
        "final_filename": final_name,
        "bytes_written": bytes_written,
        "sha256": sha_actual,
        "content_type": content_type,
        "extension": true_ext,
        "animated": animated,
        "verified_content": verified_content,
    }


# ---------------------------------------------------------------------------
# Protocol loop
# ---------------------------------------------------------------------------

def read_message(stdin) -> dict | None:
    header = stdin.read(4)
    if not header:
        return None
    if len(header) < 4:
        log("stdin closed mid-header")
        return None
    (length,) = struct.unpack("<I", header)
    if length > MAX_MESSAGE_IN_BYTES:
        log(f"inbound frame too large ({length}); aborting")
        return None
    payload = stdin.read(length)
    if len(payload) < length:
        log("stdin closed mid-body")
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"__malformed__": repr(exc)}


def write_message(stdout, msg: dict) -> None:
    payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    stdout.write(struct.pack("<I", len(payload)))
    stdout.write(payload)
    stdout.flush()


def dispatch(cfg: dict, origin: str | None, msg: dict) -> dict:
    if "__malformed__" in msg:
        return err("INVALID_MESSAGE", f"message is not valid JSON: {msg['__malformed__']}")
    try:
        msg = validate_message(msg)
    except ValidationError as exc:
        return err("INVALID_MESSAGE", str(exc))
    cmd = msg["type"]
    started = time.monotonic()
    if cmd == "health_check":
        reply = cmd_health_check(cfg, origin)
    elif cmd == "get_status":
        reply = cmd_get_status(cfg, origin)
    elif cmd == "choose_output_folder":
        reply = cmd_choose_output_folder(cfg, origin)
    elif cmd == "save_original":
        reply = cmd_save_original(cfg, origin, msg)
    else:  # unreachable; schema allows only the above
        reply = err("UNSUPPORTED_COMMAND", f"unknown command {cmd!r}")
    if cmd != "choose_output_folder" and time.monotonic() - started > PROCESSING_TIMEOUT_S:
        reply = err("TIMEOUT", f"{cmd} exceeded {PROCESSING_TIMEOUT_S}s")
    return reply


def parse_args(argv: list[str]) -> tuple[str | None, str | None]:
    """Return (origin, config_override) from launch arguments.

    Chrome invokes the host as:  <host> chrome-extension://<id>/ [--parent-window=N]
    The installer prepends our own --config flag for testing/overrides.
    """
    origin = None
    config_override = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--config" and args:
            config_override = args.pop(0)
        elif arg.startswith("chrome-extension://"):
            origin = arg.rstrip("/")
    return origin, config_override


def main(argv: list[str]) -> int:
    origin, config_override = parse_args(argv)
    cfg = load_config(config_override)
    log(f"host started (origin={origin!r}, config={config_override or config_path()})")
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            msg = read_message(stdin)
        except Exception as exc:
            log(f"read failure: {exc!r}")
            return 1
        if msg is None:
            return 0
        try:
            reply = dispatch(cfg, origin, msg)
        except Exception as exc:
            log(f"unhandled error in dispatch: {exc!r}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            reply = err("INTERNAL_ERROR", f"host internal error: {type(exc).__name__}")
        try:
            write_message(stdout, reply)
        except Exception as exc:
            log(f"write failure: {exc!r}")
            return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
