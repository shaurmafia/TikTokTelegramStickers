/* media_detect.js — TikTok DM media URL heuristics and filename suggestions.
 *
 * Detection does NOT rely on brittle CSS selectors: it matches media by URL
 * characteristics on any DOM surface that can carry it (<img> src/srcset,
 * CSS background-image, <video> src).
 *
 * DEFAULT_STRONG_PATTERNS are informed by the MIT-licensed Sticker-Grab
 * project and public network registries (see docs/ARCHITECTURE.md). They are
 * best-effort defaults pending live-session verification and are editable in
 * the Options page. Content sniffing remains the final authority for what a
 * downloaded payload actually is. */
(function (global) {
  "use strict";

  const DEFAULT_CDN_SUFFIXES = [
    "tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com",
    "tiktokv.com", "ibyteimg.com", "byteimg.com", "ttwstatic.com",
  ];

  const DEFAULT_STRONG_PATTERNS = [
    "tiktok-dm-sticker",     // p16-tiktok-dm-sticker-sign-*.ibyteimg.com
    "sticker-sign",
    "video2sticker",
    "sticker-set-frame",
    "photo-comment",
    "tos-alisg",
    "tplv-dhq",
    "tplv-gi79",
  ];

  const ANIMATED_HINTS = ["video2sticker", "awebp"];
  const IMAGE_EXTS = ["webp", "png", "gif", "jpg", "jpeg", "avif"];

  function parseUrl(url) {
    try {
      return new URL(url, location ? location.href : "https://www.tiktok.com/");
    } catch (e) {
      return null;
    }
  }

  function hostAllowed(hostname, suffixes) {
    const host = hostname.toLowerCase();
    return suffixes.some((s) => host === s || host.endsWith("." + s));
  }

  /** True when the URL matches the configured media patterns. */
  function isMediaUrl(url, patterns, suffixes) {
    const u = parseUrl(url);
    if (!u) return false;
    if (u.protocol !== "https:" && u.protocol !== "http:") return false;
    if (!hostAllowed(u.hostname, suffixes || DEFAULT_CDN_SUFFIXES)) return false;
    const hay = (u.pathname + " " + u.search).toLowerCase();
    return (patterns || DEFAULT_STRONG_PATTERNS).some((p) =>
      hay.includes(p.toLowerCase()));
  }

  /** Human-readable classification from URL shape (unverified until sniffed). */
  function classifyUrl(url) {
    const lower = (url || "").toLowerCase();
    if (lower.includes("video2sticker")) {
      return { kind: "sticker", animated: true, label: "sticker (animated, URL hint)" };
    }
    if (lower.includes("sticker-set-frame")) {
      return { kind: "sticker-frame", animated: null, label: "sticker-set frame" };
    }
    if (lower.includes("sticker")) {
      return { kind: "sticker", animated: null, label: "sticker" };
    }
    if (lower.includes("photo-comment")) {
      return { kind: "photo", animated: false, label: "photo" };
    }
    if (lower.endsWith(".gif")) {
      return { kind: "image", animated: null, label: "image (gif)" };
    }
    if (ANIMATED_HINTS.some((h) => lower.includes(h))) {
      return { kind: "sticker", animated: true, label: "sticker (animated, URL hint)" };
    }
    return { kind: "image", animated: null, label: "image" };
  }

  /** Suggest a clean filename from a media URL (no transform suffixes). */
  function suggestFilename(url) {
    const u = parseUrl(url);
    if (!u) return "tiktok-media";
    let name = decodeURIComponent(u.pathname.split("/").pop() || "");
    name = name.replace(/~tplv[^/]*$/i, "");       // TikTok transform suffix
    name = name.split("~")[0] || name;
    name = name.trim();
    const m = name.match(/^(.*)\.([a-z0-9]{2,5})$/i);
    let stem = name, ext = "";
    if (m) {
      stem = m[1];
      ext = m[2].toLowerCase();
      if (ext === "awebp") ext = "webp";           // animated WebP container
      if (!IMAGE_EXTS.includes(ext) && ext !== "mp4" && ext !== "webm") {
        ext = "";
      }
    }
    stem = stem.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/\.+$/, "").trim();
    if (!stem) stem = "tiktok-media";
    return ext ? `${stem}.${ext}` : stem;
  }

  /** Collect every candidate URL from an <img> (src, currentSrc, srcset). */
  function imgCandidateUrls(img) {
    const urls = new Set();
    for (const key of ["currentSrc", "src"]) {
      const v = img.getAttribute ? img.getAttribute(key) : null;
      const prop = img[key];
      if (prop) urls.add(prop);
      if (v && !prop) urls.add(v);
    }
    const srcset = img.getAttribute("srcset") || "";
    for (const part of srcset.split(",")) {
      const token = part.trim().split(/\s+/)[0];
      if (token) urls.add(token);
    }
    return [...urls];
  }

  /** Extract url(...) targets from a CSS background-image value. */
  function backgroundUrls(value) {
    if (!value || value === "none") return [];
    const out = [];
    const re = /url\((['"]?)(.*?)\1\)/g;
    let m;
    while ((m = re.exec(value)) !== null) {
      if (m[2]) out.push(m[2]);
    }
    return out;
  }

  const TT = (global.TT = global.TT || {});
  TT.Detect = {
    DEFAULT_CDN_SUFFIXES,
    DEFAULT_STRONG_PATTERNS,
    isMediaUrl,
    classifyUrl,
    suggestFilename,
    imgCandidateUrls,
    backgroundUrls,
    hostAllowed,
  };
})(typeof globalThis !== "undefined" ? globalThis : self);
