# TikTok DM Sticker Saver — Phase 1

Chrome (Manifest V3) extension + Python native messaging host that save
sticker media visible in **your own authenticated TikTok Direct Messages**
to a local Windows folder, byte-for-byte, with no screenshots, no
re-encoding, no cloud, no telemetry.

> **Status: architecture complete and locally tested. Live TikTok DM
> extraction is NOT yet verified** — it requires loading the extension in
> your own browser session (see Step 5). Detection patterns are best-effort
> defaults from public research and are user-editable. Details:
> [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## How it works

```
TikTok DM tab ── content script scans DOM (img/srcset + CSS backgrounds + video)
      │  you pick media in the popup
      ▼
Service worker ── fetches the original bytes, verifies type by magic bytes
      │  length-prefixed JSON (Chrome native messaging)
      ▼
Native host (Python, stdlib only) ── validates origin + schema, confines
      writes to your chosen folder, dedupes by SHA-256, writes atomically
```

What it never does: read cookies/passwords/message text, upload anything,
automate login, bypass access controls, or download media you didn't select.

## Requirements

- Windows 10/11, Python 3.9+ (tkinter included — checked by the installer),
  Chrome or another Chromium browser. No other dependencies.

## Installation

### 1. Load the extension

1. Open `chrome://extensions`, enable **Developer mode** (top right).
2. Click **Load unpacked** → select the `extension/` folder of this repo.
3. Copy the extension **ID** shown on the card (32 letters a–p).
   `python tools/compute_extension_id.py` predicts it from the path —
   verify it matches; use the value Chrome shows if it differs.

### 2. Install the native host (per-user, no admin)

```bat
cd native_host
install_host.bat --extension-id <ID you copied>
```

This registers `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.tiktokstickers.bridge`
and writes `run_host.bat` + the host manifest next to the Python script.
Restart Chrome afterwards.

Uninstall: `uninstall_host.bat --browser both --purge` (never deletes saved
media).

### 3. Choose the output folder

Open the extension's popup → ⚙ Options → **Choose output folder…**
(a native folder dialog shown by the host), then click **Save test fixture…**
to verify the whole pipeline byte-for-byte.

### 4. Run the tests

```bat
python -m unittest discover -s native_host\tests -v   :: host protocol + units
python tests\test_manifest.py -v                      :: manifest integrity
python tests\run_js_tests.py                          :: extension logic (headless Chrome)
python tests\smoke_native_host.py                     :: registry + .bat + host chain
python tests\e2e_chrome.py                            :: full e2e (needs a Chromium build that honors --load-extension; branded Chrome ≥137 ignores it — see KNOWN_LIMITATIONS)
```

### 5. Save stickers (the live-session step)

1. Open `tiktok.com`, enter a DM conversation containing stickers.
2. Click the extension icon → it lists detected media with previews and
   classification (static/animated hints; the host re-verifies from content).
3. Tick what you want → **Save selected**. Status per item shows the written
   filename, size, and duplicate/expired-URL errors. Success is reported only
   after the host confirms the write.
4. If a sticker you can see is not listed, add its URL pattern in
   Options → Detection patterns (copy a fragment of the image URL, e.g. from
   DevTools → Network), then Rescan.

## Configuration

Options page: output folder (host-enforced), naming mode (source-URL name or
prefix+timestamp), inter-download delay (defaults to 300 ms — parallel
fetching triggers TikTok CDN 403s), detection URL patterns and allowed hosts.
Duplicate policy (skip, default) lives in the host config
(`%LOCALAPPDATA%\TikTokStickersBridge\config.json`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Popup shows bridge dot red / "not connected" | Run step 2 again, check the ID, restart Chrome |
| `HOST_UNREACHABLE` | Python not on PATH for Chrome, or antivirus blocking `run_host.bat` |
| `NO_OUTPUT_DIR` | Click "Choose output folder…" in Options |
| `TOO_LARGE` | Host cap is 25 MB/file (config `max_file_mb`, max 100) |
| Stickers visible but not detected | Extend patterns in Options; see KNOWN_LIMITATIONS |
| 403 on save | Signed URL expired — Rescan and retry |

## Privacy

Everything runs locally. The extension requests `storage`, `nativeMessaging`,
`scripting` and host permissions only for tiktok.com and TikTok media CDNs.
No remote code, no analytics. Only the bytes of the media you explicitly
save pass through the native host to your disk. Referencing terms: saving
TikTok-hosted media remains subject to TikTok's Terms of Service and the
rights of the original sender.

## Docs

- [PLAN.md](PLAN.md) — verified facts, unknowns, risks, build order
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, protocol, security model
- [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) — what is and isn't verified
- [docs/PHASE1_REPORT.md](docs/PHASE1_REPORT.md) — files, test results, blockers

License: MIT (see [LICENSE](LICENSE); includes a third-party notice for the
MIT-licensed Sticker-Grab project whose public heuristics informed the
detection defaults). Not affiliated with TikTok or ByteDance.
