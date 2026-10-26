# Architecture — Phase 1

## Components

| Component | Location | Role |
|---|---|---|
| Content script (isolated) | `extension/content/content.js` | DOM scan (img/srcset, CSS `background-image`, video), URL-pattern matching, async replies to scan/fetch requests |
| Page bridge (MAIN world) | `extension/content/bridge_main.js` | Fetches `blob:` URLs created by page JS (inaccessible to the SW), returns base64 via `window.postMessage`. Fetches only blob:/same-origin |
| Service worker | `extension/background/service_worker.js` | Injects content scripts (static entry misses TikTok SPA soft-navigation, so `tabs.onUpdated`/`onActivated` re-inject on demand), fetches CDN bytes, sniffs magic bytes, calls the host, streams per-item progress |
| Popup | `extension/popup/` | Scan → list with previews → select → save → per-item status |
| Options | `extension/options/` | Output folder (via host dialog), naming rules, patterns, fixture test |
| Native host | `native_host/tiktok_sticker_bridge.py` | Stdlib-only Python; the only component that writes files |
| Installers | `native_host/install_host.py`, `uninstall_host.py` | HKCU registry per browser, `run_host.bat` launcher, host manifest with `allowed_origins` |

Shared pure logic lives in `extension/lib/` (`sniff.js`, `media_detect.js`,
`msg_schema.js`) as classic scripts (global `TT`), reused by content script,
service worker (`importScripts`) and tests.

## Detection strategy

No brittle CSS selectors. Media URLs are matched by:

1. Host suffix allowlist (`tiktok.com`, `tiktokcdn*.com`, `ibyteimg.com`, …)
2. Configurable URL substring patterns — defaults informed by the MIT-licensed
   Sticker-Grab project (`sticker-sign`, `p16-tiktok-dm-sticker`,
   `video2sticker`, `tos-alisg`, `tplv-dhq`, `tplv-gi79`, …) and by public
   network registries (e.g. `p16-tiktok-dm-sticker-sign-*.ibyteimg.com`)
3. Scanned across every surface stickers occupy: `<img>` src/currentSrc/srcset,
   CSS `background-image` (bounded to ≤8000 nodes), `<video>` src/poster

Classification is a three-stage refinement: URL hints (e.g. `video2sticker`
→ animated) → magic-byte sniff in the SW (WebP VP8X animation bit, GIF
NETSCAPE2.0, AVIF `avis`, …) → authoritative sniff in the host. The saved
extension is always derived from content, never from the suggested name.
A transformed/preview payload is saved but flagged `verified_content: false`
in the host reply and shown with an `[unknown content type]` note.

## Native messaging protocol

Frame: 4-byte LE length + UTF-8 JSON, on stdin/stdout; logs on stderr only.
`run_host.bat` launches `python -u tiktok_sticker_bridge.py` (batch file is
required because Chrome launches the manifest `path` directly on Windows).

Commands (strict schema, unknown commands/fields rejected):

- `health_check {}` → version, protocol version, output-dir configured?
- `get_status {}` → config summary
- `choose_output_folder {}` → tkinter folder dialog; persists config
- `save_original {filename, data_base64, media_type?, sha256?, overwrite?}`
  → `{status, saved, duplicate, path, final_filename, bytes_written, sha256,
  content_type, extension, animated, verified_content}`

## Host security model

- **Origin**: Chrome passes the calling origin as `argv[1]`; the host rejects
  every command unless it equals `expected_origin` in its config (written by
  the installer). Chrome's own `allowed_origins` is the outer gate.
- **Schema**: per-command allowlists for fields and types; `sha256` must be
  64-hex; base64 strictly decoded.
- **Path safety**: raw filenames containing `/ \ : ..` are rejected; the name
  is then sanitized (Windows-invalid chars, reserved device names, control
  chars, length); the final path is verified via `realpath` containment.
- **Writes**: only inside the configured output dir; temp file + `fsync` +
  `os.replace` (atomic); duplicates detected by SHA-256 (policy `skip` or
  `suffix`); size cap default 25 MB (config, ≤100 MB); inbound frame cap
  140 MB.
- **No execution**: no subprocess/shell from message input, ever.

## Extension security posture

Permissions: `storage`, `nativeMessaging`, `scripting`; host permissions only
for tiktok.com + TikTok CDNs. No remote code, no telemetry, no cookie/history
access, no automatic downloads — only user-selected items, capped at 200 per
batch, fetched sequentially with a configurable gap (CDN 403s under parallel
load are documented by the community).

## Data flow guarantees

- The popup reports "saved" only from a host reply with `status: "ok"`.
- `bytes_written` and recomputed `sha256` come from the host after `fsync`.
- Byte-for-byte fidelity is covered by `native_host/tests/test_host_protocol.py`,
  `tests/smoke_native_host.py`, and the Options "Save test fixture" button
  (fixture SHA-256 `de386e82…`, 8×8 PNG generated in-repo).
