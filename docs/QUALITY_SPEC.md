# Quality & format specification — Phase 2

## Telegram target profiles

### Static stickers (`static` profile)

| Property | Requirement | How we meet it |
|---|---|---|
| Formats | PNG or WEBP (verified by magic bytes, not extension) | Pillow encodes; validator re-sniffs |
| Canvas | Longer side exactly 512, shorter ≤ 512 | `target_dimensions()` — scales up or down as required (Telegram rejects other sizes); upscaling emits a warning |
| Size | ≤ 512 KiB | deterministic ladder: lossless WEBP → optimized PNG → lossy WEBP q-ladder from the quality mode |
| Alpha | preserved when present | premultiplied Lanczos resize (no dark fringes); alpha is re-verified by the validator |

Encoding ladder (recorded per file in the report): both lossless candidates
are tried; the first that fits wins (lossless WEBP preferred, PNG fallback).
If neither fits, WEBP lossy walks the quality-mode ladder from highest to
lowest and the first compliant quality is kept. `quality_first` never
reaches a compliant size on busy sources → output is kept and marked
`needs_review` rather than being silently degraded further.

### Video stickers (`video` profile)

| Property | Requirement | How we meet it |
|---|---|---|
| Container/codec | WebM / VP9 (verified by ffprobe) | libvpx-vp9, two-pass ABR |
| Size | ≤ 256 KiB | bitrate = 97% of the byte budget ÷ duration; on overshoot: bitrate ×= actual/budget × 0.95, retry (mode-capped); documented fps fallbacks 20 → 15 on later attempts |
| Duration | ≤ 3.0 s (+0.06 s tolerance) | user policy: `trim_first` (first 3 s) or `speed_up` (setpts) — always warned, never silent |
| Frame rate | ≤ 30 fps | `fps=30` resample when the source exceeds it (warned) |
| Audio | none | `-an -sn -dn`; validator re-checks |
| Alpha | preserved when source has alpha | `yuva420p` + **`-auto-alt-ref 0`** (alt-ref frames destroy alpha) + `alpha_mode=1` stream metadata; VP8/VP9 sources are decoded with the **libvpx decoder** (the native VP9 decoder silently ignores alpha) |
| Canvas | longer side exactly 512, even values | `scale='512':'-2'` (landscape) / `scale='-2':'512'` (portrait), lanczos+accurate_rnd |

### TGS — intentionally not offered

TGS is a vector (Lottie) format; raster GIF/WebM sources cannot be converted
without reconstructing the artwork. The profile registry is extensible, but
no automatic GIF→TGS path is claimed.

## Quality modes

| Mode | WEBP ladder | VP9 cpu-used | Attempts | Trade-off |
|---|---|---|---|---|
| quality_first | 95→50 | 2 (slow/best) | 4 | best detail; may miss the size cap → flagged for review |
| balanced | 90→40 | 3 | 4 | near-transparent quality loss, reliable size compliance |
| size_first | 80→30 | 4 | 3 | visibly softer on busy animations, always small |

All settings are deterministic: identical input + mode → byte-identical
output (covered by `test_quality_modes_deterministic`).

## VP9 alpha — implementation notes (hard-won)

- FFmpeg's **native VP9 decoder ignores alpha** and reports `yuv420p`; ffprobe
  therefore cannot be trusted for alpha. All alpha verification decodes with
  `-c:v libvpx-vp9` and checks actual transparent pixels.
- Without `-auto-alt-ref 0` alt-reference frames corrupt alpha on some
  streams; it is always disabled for alpha encodes.
- Source alpha for VP8/VP9 inputs is detected by decoding a frame via libvpx,
  not by pix_fmt.

## Per-file reports

Each conversion writes `reports/<name>-<UTC>.json`: source & output SHA-256,
original copy path, full source/output metadata, warnings, every encoding
attempt with byte counts, validator check list, telegram_ready flag, timing.
Originals are copied unchanged to `originals/` before anything else runs and
are never modified or deleted.
