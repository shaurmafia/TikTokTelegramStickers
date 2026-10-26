/* service_worker.js — orchestration hub (MV3).
 *
 * Responsibilities:
 *  - inject content scripts on TikTok tabs (static injection misses SPA soft
 *    navigation, so tabs.onUpdated/onActivated re-check and inject on demand)
 *  - relay strictly validated commands to the native messaging host
 *  - fetch selected media bytes (service worker for CDN https, page bridge
 *    for blob:/same-origin), sniff content, and stream per-item progress to
 *    the popup
 * Nothing leaves the machine except the media fetch itself. */

importScripts("../lib/sniff.js", "../lib/media_detect.js", "../lib/msg_schema.js");

const SETTINGS_KEY = "settings";

const DEFAULT_SETTINGS = {
  patterns: TT.Detect.DEFAULT_STRONG_PATTERNS.slice(),
  suffixes: TT.Detect.DEFAULT_CDN_SUFFIXES.slice(),
  namingMode: "suggested",     // "suggested" | "prefix_ts"
  namingPrefix: "sticker_",
  fetchGapMs: 300,
};

const FETCH_TIMEOUT_MS = 30000;

/* ---------------- settings ---------------- */

async function getSettings() {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  const s = stored[SETTINGS_KEY] || {};
  return { ...DEFAULT_SETTINGS, ...s };
}

/* ---------------- content script injection ---------------- */

const TIKTOK_RE = /^https:\/\/([^/]+\.)?tiktok\.com\//i;

async function pingContent(tabId) {
  try {
    const r = await chrome.tabs.sendMessage(tabId, { type: "ping" });
    return !!(r && r.ok);
  } catch (e) {
    return false;
  }
}

async function ensureInjected(tabId) {
  if (await pingContent(tabId)) return;
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content/bridge_main.js"],
    world: "MAIN",
    injectImmediately: true,
  });
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["lib/media_detect.js", "content/content.js"],
    injectImmediately: true,
  });
  if (!(await pingContent(tabId))) {
    throw new Error("content script did not respond after injection");
  }
}

async function getTikTokTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id || !tab.url || !TIKTOK_RE.test(tab.url)) return null;
  return tab;
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  const url = changeInfo.url || (changeInfo.status === "complete" && tab.url);
  if (url && TIKTOK_RE.test(url)) {
    ensureInjected(tabId).catch((e) => console.warn("[ttstk] inject:", e.message));
  }
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab && tab.url && TIKTOK_RE.test(tab.url)) {
      ensureInjected(tabId).catch(() => {});
    }
  } catch (e) { /* tab may be gone */ }
});

chrome.runtime.onInstalled.addListener(async () => {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  if (!stored[SETTINGS_KEY]) {
    await chrome.storage.local.set({ [SETTINGS_KEY]: DEFAULT_SETTINGS });
  }
});

/* ---------------- native messaging ---------------- */

function callHost(command) {
  const check = TT.Schema.validateHostCommand(command);
  if (!check.ok) {
    return Promise.resolve({ status: "error", code: "INVALID_MESSAGE",
                             message: check.error });
  }
  return new Promise((resolve) => {
    chrome.runtime.sendNativeMessage(TT.Schema.HOST_NAME, command, (reply) => {
      const err = chrome.runtime.lastError;
      if (err) {
        resolve({ status: "error", code: "HOST_UNREACHABLE",
                  message: err.message });
      } else {
        resolve(reply || { status: "error", code: "HOST_NO_REPLY",
                           message: "native host returned nothing" });
      }
    });
  });
}

/* ---------------- media fetching ---------------- */

function bytesToBase64(bytes) {
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function fetchWithTimeout(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  return fetch(url, { credentials: "include", signal: controller.signal })
    .finally(() => clearTimeout(timer));
}

async function fetchViaBridge(tabId, url) {
  const reply = await chrome.tabs.sendMessage(tabId, { type: "page_fetch", url });
  if (!reply || !reply.ok) {
    throw new Error((reply && reply.error) || "page bridge unavailable");
  }
  return Uint8Array.from(atob(reply.dataBase64), (c) => c.charCodeAt(0));
}

async function fetchMediaBytes(item, tabId) {
  if (item.url.startsWith("blob:")) {
    return fetchViaBridge(tabId, item.url);
  }
  const resp = await fetchWithTimeout(item.url);
  if (!resp.ok) {
    const hint = resp.status === 403
      ? "signed URL expired or denied (403) — rescan and retry"
      : `HTTP ${resp.status}`;
    throw new Error(hint);
  }
  return new Uint8Array(await resp.arrayBuffer());
}

/* ---------------- save pipeline ---------------- */

let cancelRequested = false;

function timestampStem(now) {
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-` +
         `${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}` +
         `-${p(now.getMilliseconds(), 3)}`;
}

function stemOf(filename) {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(0, dot) : filename;
}

async function runSave(items, tabId, sendProgress) {
  const settings = await getSettings();
  cancelRequested = false;
  const summary = { saved: 0, duplicates: 0, failed: 0, cancelled: 0 };
  let tsStem = null;

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (cancelRequested) {
      summary.cancelled++;
      sendProgress(item.id, "cancelled", "cancelled by user");
      continue;
    }
    sendProgress(item.id, "working", "fetching media…");
    try {
      const bytes = await fetchMediaBytes(item, tabId);
      const sniffed = TT.Sniff.sniff(bytes);
      const ext = sniffed ? sniffed.ext : "bin";
      const sha256 = await crypto.subtle.digest("SHA-256", bytes)
        .then((buf) => [...new Uint8Array(buf)]
          .map((b) => b.toString(16).padStart(2, "0")).join(""));

      let filename;
      if (settings.namingMode === "prefix_ts") {
        if (tsStem === null) tsStem = timestampStem(new Date());
        filename = `${settings.namingPrefix}${tsStem}` +
                   (items.length > 1 ? `-${i + 1}` : "") + `.${ext}`;
      } else {
        filename = `${stemOf(item.suggestedFilename)}.${ext}`;
      }

      sendProgress(item.id, "working", "writing via native host…");
      const reply = await callHost({
        type: "save_original",
        filename,
        data_base64: bytesToBase64(bytes),
        media_type: sniffed ? sniffed.mime : "application/octet-stream",
        sha256,
        overwrite: false,
      });

      if (reply.status !== "ok") {
        summary.failed++;
        sendProgress(item.id, "failed",
          `${reply.code}: ${reply.message || "host error"}`);
      } else if (reply.duplicate && !reply.saved) {
        summary.duplicates++;
        sendProgress(item.id, "duplicate",
          `already saved as ${reply.final_filename}`);
      } else {
        summary.saved++;
        const note = reply.duplicate ? " (renamed, content duplicate)" : "";
        sendProgress(item.id, "saved",
          `${reply.final_filename}${note} — ${reply.bytes_written} bytes` +
          (reply.verified_content ? "" : " [unknown content type]"));
      }
    } catch (e) {
      summary.failed++;
      sendProgress(item.id, "failed", e && e.message ? e.message : String(e));
    }
    if (i < items.length - 1 && settings.fetchGapMs > 0) {
      await new Promise((r) => setTimeout(r, settings.fetchGapMs));
    }
  }
  return summary;
}

/* ---------------- message router ---------------- */

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (!msg || typeof msg.type !== "string") {
      sendResponse({ ok: false, error: "bad message" });
      return;
    }
    try {
      switch (msg.type) {
        case "ping":
          sendResponse({ ok: true });
          break;

        case "scan": {
          const tab = await getTikTokTab();
          if (!tab) {
            sendResponse({ ok: false, error: "active tab is not tiktok.com" });
            return;
          }
          await ensureInjected(tab.id);
          const reply = await chrome.tabs.sendMessage(tab.id, { type: "scan" });
          sendResponse(reply);
          break;
        }

        case "host": {
          sendResponse(await callHost(msg.command));
          break;
        }

        case "save": {
          const tab = await getTikTokTab();
          if (!tab || !Array.isArray(msg.items) || msg.items.length === 0) {
            sendResponse({ ok: false, error: "nothing to save" });
            return;
          }
          const sendProgress = (id, state, detail) => {
            chrome.runtime.sendMessage(
              { type: "save_progress", id, state, detail })
              .catch(() => { /* popup may be closed */ });
          };
          const summary = await runSave(msg.items.slice(0, 200), tab.id,
                                        sendProgress);
          sendResponse({ ok: true, summary });
          break;
        }

        case "cancel_save":
          cancelRequested = true;
          sendResponse({ ok: true });
          break;

        default:
          sendResponse({ ok: false, error: `unknown request ${msg.type}` });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e && e.message ? e.message : String(e) });
    }
  })();
  return true;  // async sendResponse
});
