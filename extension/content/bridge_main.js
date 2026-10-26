/* bridge_main.js — MAIN-world fetch bridge (runs in the page's own world).
 *
 * Some TikTok media is referenced as blob: URLs created by page JavaScript.
 * Those blobs belong to the page's world, so the isolated content script (and
 * the service worker) cannot fetch them directly. This tiny bridge fetches
 * ONLY blob: URLs and same-origin (tiktok.com) URLs on request and returns
 * the bytes as base64 via window.postMessage.
 *
 * It fetches nothing on its own initiative, exposes no globals, and ignores
 * any message that is not an exact match for the protocol below. */
(function () {
  "use strict";
  if (window.__TTSTK_BRIDGE__) return;
  window.__TTSTK_BRIDGE__ = true;

  const REQUEST = "ttstk-page-request";
  const RESPONSE = "ttstk-page-response";

  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      binary += String.fromCharCode.apply(
        null, bytes.subarray(i, i + CHUNK));
    }
    return btoa(binary);
  }

  function sameOrigin(url) {
    try {
      return new URL(url, location.href).origin === location.origin;
    } catch (e) {
      return false;
    }
  }

  window.addEventListener("message", async (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.source !== REQUEST || typeof msg.id !== "string"
        || typeof msg.url !== "string") {
      return;
    }
    let reply;
    try {
      const u = new URL(msg.url, location.href);
      if (u.protocol !== "blob:" && !sameOrigin(u.href)) {
        reply = { ok: false, error: "bridge refuses non-blob, cross-origin URLs" };
      } else {
        const resp = await fetch(u.href, { credentials: "include" });
        if (!resp.ok) {
          reply = { ok: false, error: `fetch failed with HTTP ${resp.status}` };
        } else {
          reply = { ok: true, dataBase64: toBase64(await resp.arrayBuffer()) };
        }
      }
    } catch (e) {
      reply = { ok: false, error: `bridge fetch error: ${e && e.message}` };
    }
    window.postMessage({
      source: RESPONSE, id: msg.id, ...reply,
    }, window.location.origin);
  });
})();
