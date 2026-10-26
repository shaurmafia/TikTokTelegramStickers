# Known limitations — Phase 1 (2026-10-26)

## Not yet verified (requires your authenticated TikTok session)

1. **Live sticker extraction is unverified.** No authenticated TikTok DM
   session was available in this development environment, and the spec (and
   privacy rules) forbid automated login or using stored credentials.
   Therefore: the DOM scan, CDN fetch, and save pipeline are tested against
   synthetic fixtures only. Do not assume the default detection patterns are
   complete — TikTok rotates CDN hosts and `~tplv` transform suffixes.
2. Whether the DOM-visible sticker URL yields the **original** quality or a
   transformed variant. If a transformed variant is all that's reachable, the
   app labels it honestly (`verified_content: false` / "unknown content
   type") rather than claiming originality. Rewriting `~tplv…` parameters to
   obtain the untouched asset is a Phase 2 task pending live confirmation.
3. `blob:`-based stickers are handled by the MAIN-world bridge but not
   exercised live.
4. SPA re-injection on tiktok.com soft navigation is implemented
   (`tabs.onUpdated`/`onActivated` + `chrome.scripting`) but not observed live.

## Environment blockers

5. **Branded Chrome ≥137 ignores `--load-extension`**, so the full e2e
   (`tests/e2e_chrome.py`, which drives Chrome via CDP) cannot run on this
   machine's Chrome. It passes on Chromium builds that honor the flag.
   Compensating coverage: `tests/smoke_native_host.py` launches the host
   through the exact registry→manifest→`run_host.bat` chain Chrome uses, and
   protocol tests drive the real host process over stdio. The final
   Chrome-side link (popup click → SW → host) needs the manual Step 5 in the
   README. The Options-page "Save test fixture" button exercises everything
   except DOM detection inside real Chrome.
6. `choose_output_folder` requires tkinter (bundled with python.org Windows
   installs; verified present here). Headless/server Python without tkinter
   gets a clear `DIALOG_UNAVAILABLE` error.

## Design constraints

7. Signed CDN URLs expire within minutes; the extension fetches at save time
   and surfaces `403` as "rescan and retry". URLs are never persisted.
8. Sequential fetching with a 300 ms gap (parallel fetches cause sporadic
   CDN 403s per community reports). Large batches are slower by design.
9. File cap 25 MB per item (config up to 100 MB); replies to the extension
   are <1 MB (Chrome native-messaging limit).
10. Only files inside the configured output dir are written; media is saved
    flat (no subdirectories) in Phase 1.
11. If the MV3 service worker is suspended mid-batch, remaining items must be
    retried manually (popup shows per-item state; progress is not durable).
12. The unpacked extension ID is path-derived; moving the repo folder requires
    re-running `install_host.bat` with the (new) ID.

## Phase 2 checklist (live-session milestone)

- [ ] Load extension in your Chrome, open a DM with stickers, run a scan.
- [ ] If items are missing: copy URL fragments from DevTools → Network into
      Options → Detection patterns, rescan.
- [ ] Save one static and one animated sticker; confirm the host's
      `content_type`/`animated` flags match expectation.
- [ ] Decide whether `~tplv` URL rewriting is needed for original quality.
- [ ] Update PLAN.md §5 unknowns with the findings.
