/* content.js — isolated content script for TikTok DM pages.
 *
 * Scans the DOM for media matching the configured URL patterns (across
 * <img> src/srcset, CSS background-image, and <video> sources), answers
 * scan requests from the popup/service worker, and relays blob: fetches to
 * the MAIN-world bridge. It does not modify the page. */
(function () {
  "use strict";
  if (window.__TTSTK_CONTENT__) return;
  window.__TTSTK_CONTENT__ = true;

  const MAX_NODES_FOR_CSS_SCAN = 8000;

  let patterns = null;   // lazily loaded from storage; falls back to defaults
  let suffixes = null;

  async function loadPatterns() {
    try {
      const stored = await chrome.storage.local.get(["patterns", "suffixes"]);
      if (Array.isArray(stored.patterns) && stored.patterns.length) {
        patterns = stored.patterns;
      }
      if (Array.isArray(stored.suffixes) && stored.suffixes.length) {
        suffixes = stored.suffixes;
      }
    } catch (e) {
      /* fall back to defaults */
    }
    patterns = patterns || TT.Detect.DEFAULT_STRONG_PATTERNS;
    suffixes = suffixes || TT.Detect.DEFAULT_CDN_SUFFIXES;
  }

  function onDmPage() {
    return /^\/messages/.test(location.pathname);
  }

  function makeId(url) {
    let h = 5381;
    for (let i = 0; i < url.length; i++) {
      h = ((h << 5) + h + url.charCodeAt(i)) | 0;
    }
    return "m" + (h >>> 0).toString(16) + "_" + url.length.toString(36);
  }

  function addItem(map, url, source, previewEl) {
    if (!url || url.startsWith("data:")) return;
    const abs = new URL(url, location.href).href;
    if (map.has(abs)) return;
    if (!TT.Detect.isMediaUrl(abs, patterns, suffixes)) return;
    const cls = TT.Detect.classifyUrl(abs);
    map.set(abs, {
      id: makeId(abs),
      url: abs,
      source,                       // "img" | "css" | "video"
      previewUrl: source === "video" ? "" : abs,
      classification: cls,
      suggestedFilename: TT.Detect.suggestFilename(abs),
    });
  }

  function scanMedia() {
    const found = new Map();

    for (const img of document.querySelectorAll("img")) {
      for (const u of TT.Detect.imgCandidateUrls(img)) {
        addItem(found, u, "img");
      }
    }
    for (const video of document.querySelectorAll("video")) {
      for (const u of [video.currentSrc, video.src, video.poster]) {
        addItem(found, u, "video");
      }
    }
    if (document.querySelectorAll("*").length <= MAX_NODES_FOR_CSS_SCAN) {
      for (const el of document.querySelectorAll("*")) {
        const bg = getComputedStyle(el).backgroundImage;
        for (const u of TT.Detect.backgroundUrls(bg)) {
          addItem(found, u, "css");
        }
      }
    }
    return [...found.values()];
  }

  /* ---- MAIN-world blob bridge relay ---------------------------------- */

  let bridgeSeq = 0;
  const pendingBridges = new Map();

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.source !== "ttstk-page-response") return;
    const pending = pendingBridges.get(msg.id);
    if (pending) {
      pendingBridges.delete(msg.id);
      pending(msg);
    }
  });

  function fetchViaPageBridge(url) {
    return new Promise((resolve, reject) => {
      const id = "b" + Date.now().toString(36) + "_" + (bridgeSeq++);
      const timer = setTimeout(() => {
        pendingBridges.delete(id);
        reject(new Error("page bridge timed out"));
      }, 20000);
      pendingBridges.set(id, (reply) => {
        clearTimeout(timer);
        if (reply.ok) resolve(reply.dataBase64);
        else reject(new Error(reply.error || "page bridge failed"));
      });
      window.postMessage(
        { source: "ttstk-page-request", id, url }, window.location.origin);
    });
  }

  /* ---- message surface ------------------------------------------------ */

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    (async () => {
      if (!msg || typeof msg.type !== "string") {
        sendResponse({ ok: false, error: "bad message" });
        return;
      }
      if (msg.type === "ping") {
        sendResponse({ ok: true, loaded: true });
      } else if (msg.type === "scan") {
        await loadPatterns();
        if (!onDmPage()) {
          sendResponse({ ok: true, onDmPage: false, items: [] });
          return;
        }
        try {
          sendResponse({ ok: true, onDmPage: true, items: scanMedia() });
        } catch (e) {
          sendResponse({ ok: false, error: `scan failed: ${e && e.message}` });
        }
      } else if (msg.type === "page_fetch") {
        try {
          const dataBase64 = await fetchViaPageBridge(msg.url);
          sendResponse({ ok: true, dataBase64 });
        } catch (e) {
          sendResponse({ ok: false, error: e && e.message });
        }
      } else {
        sendResponse({ ok: false, error: `unknown request ${msg.type}` });
      }
    })();
    return true;  // async sendResponse
  });
})();
