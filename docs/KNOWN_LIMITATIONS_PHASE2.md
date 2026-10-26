# Known limitations — Phase 2 (2026-10-26)

## Unavoidable lossy conversions

1. **Static sources larger than 512 KiB after lossless encoding** go through
   lossy WEBP; the applied quality and every attempt are recorded in the
   report. There is no way to hit Telegram's cap losslessly for such sources.
2. **Duration > 3 s** requires trimming or speeding up — the app never does
   this silently: the policy is user-selected and the change is warned in the
   queue and the report.
3. **Frame rate > 30 fps** is resampled to 30 fps. Temporal smoothness above
   the cap cannot survive Telegram's limits.
4. **Upscaling small sources to 512** (Telegram's canvas requirement) softens
   detail; warned and unavoidable for sources under 512 px.
5. Animated sources are re-encoded (VP9), so pixel-exact frame fidelity is
   not preserved — the goal is highest perceptual quality within the caps.
6. **TGS outputs are not supported** (vector format; raster conversion would
   require artwork reconstruction).

## Environment / implementation

7. FFmpeg must be available (PATH or `%LOCALAPPDATA%\TikTokStickersToolkit\ffmpeg*\bin`).
   The **gyan "essentials" build works for encoding**; alpha is verified by
   decoding, and both essentials and full builds passed the alpha round-trip
   once decoded via libvpx.
8. VP9 alpha depends on FFmpeg behavior that has changed across releases
   (`-auto-alt-ref 0` requirement, native decoder ignoring alpha). The
   validator catches regressions by decoding pixels, not trusting flags.
9. The GUI auto-ingest watches the **extension output folder** (Phase 1 host
   config) by polling with a 1.5 s stability debounce. There is no push
   event from the host (Chrome native messaging is one-shot from the
   extension); folder-watching is the documented fallback per spec.
10. GUI automated coverage is offscreen smoke-level (build, queue, convert,
    responsiveness, failure marking). Visual layout, real drag-and-drop
    gestures, and animation playback require manual inspection.
11. Telegram upload behavior (server-side acceptance of produced files) is
    **not tested** — no bot/token is involved by design; the validators
    implement the published sticker requirements client-side.
12. `quality_first` may leave the WEBM above 256 KiB → file is saved and
    marked `needs_review` (moved to `failed/` only when validation fails).
13. Folder watch uses polling (no extra dependency); very large watched
    folders (10k+ files) will scan slowly.

## Manual verification checklist (requires a human)

- [ ] Inspect 3–5 representative outputs visually (static + animated, alpha
      edges especially) — automated tests check pixels programmatically but
      aesthetic quality needs eyes.
- [ ] Upload one static and one video sticker via Telegram's sticker
      management flow to confirm server acceptance.
- [ ] Confirm drag-and-drop ergonomics and window resizing on a real desktop.
