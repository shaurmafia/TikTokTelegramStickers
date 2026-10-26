# Phase 1 Implementation Plan — TikTok DM Chrome Extension & Local Download Bridge

Date: 2026-10-26
Status: Implemented (live TikTok session verification still pending — see Unknowns)

## 1. Environment findings (verified on this machine)

| Item | Status | Detail |
|---|---|---|
| Python | ✅ 3.13.2 | `C:\Users\shura\AppData\Local\Programs\Python\Python313\python.exe`, pip 26.1.2, tkinter 8.6 present |
| Git | ✅ 2.51.2.windows.1 | Project folder is empty; parent tree is a personal "vault backup" repo (branch `shura-blocks-ai`). A **fresh, independent Git repo is initialized inside this project folder** so existing history is untouched. |
| Chrome | ✅ | `C:\Program Files\Google\Chrome\Application\chrome.exe` (Edge also present as Chromium fallback) |
| Node.js | ❌ not installed | Not required: extension JS runs inside Chrome; the JS unit tests run in **headless Chrome** driven by a Python test script, so no Node dependency exists anywhere in the toolchain. |
| Dependencies to install | none | Extension: none. Native host: Python stdlib only (zlib/hashlib/base64/json/tkinter/ctypes/unicodedata). |

## 2. Reference repository review — Sticker-Grab

- URL: https://github.com/kenolabs11-sys/Sticker-Grab — **MIT license** (verified on the repo page). Code may be referenced/adapted with attribution; we wrote an original implementation and credit its DOM/CDN heuristics in `docs/ARCHITECTURE.md` and `LICENSE` notes.
- Architecture: only the browser extension is open source; its desktop app is closed-source and is reached via a local HTTP server (`host_permissions: http://127.0.0.1:8765/*`), not Chrome Native Messaging. Our project deliberately uses **Chrome Native Messaging** per the Phase 1 spec.
- Practical heuristics harvested from its (MIT) `content.js`, cross-checked with public network registries:
  - TikTok DM sticker URLs carry substrings such as `p16-tiktok-dm-sticker`, `sticker-sign`, `tos-alisg`, `tplv-dhq`, `tplv-gi79`. TikTok rotates CDN subdomains, so the list must be configurable, not hard-coded.
  - Stickers appear both as `<img src/srcset>` and as **CSS `background-image`** on arbitrary elements — both passes are required.
  - URL substrings hint the media class: `video2sticker` → animated, `-full` → sticker, `sticker-set-frame` → sticker-set frame, `photo-comment` → photo; `.awebp` → animated WebP; a `~tplv…` transform suffix should be stripped for filenames.
  - Signed CDN URLs expire quickly (community-documented 403s when reused, see drawrowfly/tiktok-scraper issue #308) → the bridge must fetch bytes **immediately upon selection**, never persist URLs.
  - Aggressive parallel fetching (≥4 workers) caused sporadic CDN 403s → downloads run sequentially with a small gap.

## 3. Architecture (summary; full detail in docs/ARCHITECTURE.md)

```
TikTok DM page (tab)
├─ MAIN-world bridge  (bridge_main.js)   fetches blob:/same-origin media on request, returns base64
└─ ISOLATED content script (content.js)  scans DOM (img/srcset + CSS backgrounds), selection overlay,
                                         classifies by URL heuristics, talks to SW
Chrome service worker (service_worker.js) orchestrates: fetch https media bytes, sniff magic bytes,
                                         base64-encode, chrome.runtime.sendNativeMessage(...)
Popup (popup.js)  list/preview/select, per-item status, progress, retry
Options (options.js) choose folder via host, naming rules, duplicate policy, test-fixture save
        │  length-prefixed JSON over stdio
Native host tiktok_sticker_bridge.py (stdlib only)
  - validates origin (argv[1]) against installed config, strict per-command message schema,
    command allowlist: health_check / choose_output_folder / get_status / save_original
  - writes ONLY inside the configured output dir; realpath containment; traversal rejected
  - sha256 duplicate detection, collision suffixing, extension derived from magic bytes,
    atomic write (tmp + os.replace), size caps, stderr-only logging
```

Manifest V3: `permissions: ["storage", "nativeMessaging", "scripting"]` (minimum set). `host_permissions`: `*.tiktok.com` (SPA injection via `chrome.scripting`) + the media CDN suffixes (fetched bytes flow through the service worker). No remote code, no analytics, nothing leaves the machine except the media fetch the user triggers.

## 4. Verified facts

1. Python 3.13.2 + tkinter 8.6, Git, Chrome present; no Node (not needed; see §1).
2. Sticker-Grab is MIT-licensed; only its extension is open source; it uses a localhost HTTP bridge, not native messaging (repo README + manifest, fetched 2026-10-26).
3. Third-party network registry (netify.ai) shows TikTok DM stickers are served from signed ByteDance image-CDN hostnames such as `p16-tiktok-dm-sticker-sign-useast2a.ibyteimg.com`; community issue reports confirm signed CDN URLs expire (403 on reuse).
4. Sticker-Grab's content script demonstrates the DOM surfaces stickers occupy (`<img>`+`srcset` and CSS `background-image`) and the URL substring classes above.
5. Chrome native messaging on Windows: host manifest registered under `HKCU\Software\Google\Chrome\NativeMessagingHosts\<name>` (no admin rights needed); Chrome passes the calling origin as `argv[1]`; messages are 4-byte little-endian length-prefixed UTF-8 JSON on stdin/stdout; extension→host messages may be large (media as base64), host→extension replies must stay < 1 MB.
6. `choose_output_folder` can be implemented with the Python stdlib (tkinter `filedialog.askdirectory`) — no shell command execution, no subprocess spawning from extension input.

## 5. Unknowns (cannot be resolved without the user's authenticated TikTok session)

1. **Live DOM structure of TikTok DM stickers is unverified.** No authenticated session was available in this environment (logging in programmatically is forbidden by the spec; using stored credentials without authorization is forbidden by the privacy constraints). Detection therefore ships with multi-signal heuristics (CDN substrings + `srcset` + CSS backgrounds + content sniffing) and a user-editable pattern list, but **live extraction is not yet verified** — the spec's fallback path (testable architecture + fixtures first) is followed.
2. Whether the "original" sticker variant is always reachable from the DOM URL, or whether a higher-quality variant must be derived by rewriting `~tplv…` transform parameters (documented approach in Sticker-Grab; needs one live session to confirm).
3. Whether stickers appear as `blob:` URLs in some message types (handled via the MAIN-world bridge path, but untested live).
4. Exact SPA navigation behavior of tiktok.com/messages (the extension injects both statically and on `tabs.onUpdated`/`onActivated` to cover soft navigation; needs one live session to confirm).

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| TikTok rotates/renames CDN hosts → detection misses | Pattern list stored in `chrome.storage` and editable in Options; content sniffing is the final authority for classification, so even a "plain image" fallback is labeled accurately |
| Signed URLs expire between scan and click | Media list is rebuilt on demand; fetch happens at save time; expired-URL fetch failures produce a clear "URL expired — rescan" error and the item stays retryable |
| CDN 403 under parallel load | Sequential downloads with a 300 ms gap |
| Extension reports success falsely | Popup/Options show success **only** after the host's written-and-verified reply (`sha256` recomputed by host, `bytes_written` returned); fixture save in Options verifies byte-for-byte |
| Malicious/buggy messages to host | Strict schema validation, command allowlist, origin check on `argv[1]`, output-dir containment, size caps, no subprocess/shell from message input |
| Large stickers inflate via base64 | Raw-byte cap (default 25 MB, configurable ≤ 100 MB) enforced on both sides; host re-checks decoded size |

## 7. Build order (each step verified before the next)

1. Repo scaffolding (`.gitignore`, LICENSE skeleton, docs) + `git init` in project folder.
2. Native host `tiktok_sticker_bridge.py` + unit/protocol tests → **run tests** (host is the riskiest security surface, so it goes first).
3. Windows installer/uninstaller (HKCU registry, per-user, no admin) → install with dev ID, smoke-test `health_check`.
4. Extension: manifest, libs (sniff/media-detect/schema), content scripts, service worker, popup, options, icons → **run JS tests in headless Chrome** + manifest sanity script.
5. End-to-end fixture flow: Options page "Save test fixture" → host writes → byte-compare (manual step documented; automated equivalent covered by protocol tests).
6. Docs: README, ARCHITECTURE, KNOWN_LIMITATIONS, PHASE1_REPORT.

## 8. Phase 2 preview (for the live-session milestone)

With the user's authenticated session: (a) run the extension's built-in DOM diagnostics on a real `/messages` conversation and export the scan report; (b) confirm/extend the CDN pattern list; (c) verify original-variant URL rewriting for one static and one animated sticker; (d) mark the "live verified" checklist in KNOWN_LIMITATIONS.md.
