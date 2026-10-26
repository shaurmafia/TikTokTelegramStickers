/* popup.js — media list, selection, save orchestration UI. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const listEl = $("#list");
const noticeEl = $("#notice");
const summaryEl = $("#summary");
const saveBtn = $("#save");
const cancelBtn = $("#cancel");
const rescanBtn = $("#rescan");

let mediaItems = [];
let saving = false;

function send(msg) {
  return chrome.runtime.sendMessage(msg);
}

function setNotice(text, isError = false) {
  noticeEl.textContent = text;
  noticeEl.classList.toggle("error", isError);
  noticeEl.classList.toggle("hidden", !text);
}

function setBridgeDot(state) {
  const dot = $("#bridge");
  dot.className = "dot " + (state || "");
  dot.title = {
    "": "checking native bridge…",
    ok: "native bridge connected",
    err: "native bridge unreachable — open Options",
  }[state || ""] || "";
}

async function checkBridge() {
  setBridgeDot("");
  const reply = await send({ type: "host", command: { type: "health_check" } });
  setBridgeDot(reply && reply.status === "ok" ? "ok" : "err");
  return reply;
}

function rowFor(item) {
  const row = document.createElement("label");
  row.className = "item";
  row.dataset.id = item.id;

  const box = document.createElement("input");
  box.type = "checkbox";
  box.addEventListener("change", updateSaveButton);

  const thumb = document.createElement("div");
  thumb.className = "thumb";
  if (item.previewUrl && item.source !== "video") {
    const img = document.createElement("img");
    img.src = item.previewUrl;
    img.width = 40;
    img.height = 40;
    img.style.objectFit = "contain";
    img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => img.remove());
    thumb.appendChild(img);
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = item.suggestedFilename;
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent = `${item.classification.label} · via ${item.source}`;
  if (item.classification.animated) {
    const badge = document.createElement("span");
    badge.className = "badge animated";
    badge.textContent = "animated";
    sub.appendChild(document.createTextNode(" "));
    sub.appendChild(badge);
  }
  const status = document.createElement("div");
  status.className = "status";
  status.dataset.status = "";
  meta.append(name, sub, status);

  row.append(box, thumb, meta);
  return row;
}

function updateSaveButton() {
  const n = listEl.querySelectorAll("input:checked").length;
  saveBtn.disabled = saving || n === 0;
  saveBtn.textContent = n ? `Save selected (${n})` : "Save selected";
}

function renderItems() {
  listEl.textContent = "";
  for (const item of mediaItems) {
    listEl.appendChild(rowFor(item));
  }
  updateSaveButton();
}

function setStatus(id, state, detail) {
  const row = listEl.querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!row) return;
  const el = row.querySelector(".status");
  el.textContent = detail;
  el.className = `status ${state}`;
}

async function rescan() {
  setNotice("");
  summaryEl.classList.add("hidden");
  listEl.textContent = "";
  setNotice("Scanning this page…");
  const reply = await send({ type: "scan" });
  if (!reply || !reply.ok) {
    setNotice(reply && reply.error ? reply.error : "scan failed", true);
    return;
  }
  if (!reply.onDmPage) {
    setNotice("Open a TikTok Direct Messages conversation, then Rescan.");
    return;
  }
  mediaItems = reply.items || [];
  if (!mediaItems.length) {
    setNotice("No matching media found. If stickers are visible, add their " +
              "URL patterns in Options (see KNOWN_LIMITATIONS).");
    return;
  }
  setNotice("");
  renderItems();
}

async function saveSelected() {
  const selected = [];
  for (const row of listEl.querySelectorAll(".item")) {
    if (row.querySelector("input").checked) {
      const item = mediaItems.find((m) => m.id === row.dataset.id);
      if (item) selected.push(item);
    }
  }
  if (!selected.length) return;

  saving = true;
  cancelBtn.classList.remove("hidden");
  cancelBtn.disabled = false;
  saveBtn.disabled = true;
  for (const item of selected) setStatus(item.id, "working", "queued…");

  const onProgress = (msg) => {
    if (msg && msg.type === "save_progress") {
      setStatus(msg.id, msg.state, msg.detail);
    }
  };
  chrome.runtime.onMessage.addListener(onProgress);

  // The save reply arrives after every item has been processed; progress
  // messages have already updated the rows by then.
  const reply = await send({ type: "save", items: selected });
  chrome.runtime.onMessage.removeListener(onProgress);

  saving = false;
  cancelBtn.classList.add("hidden");
  updateSaveButton();

  if (reply && reply.ok) {
    const s = reply.summary;
    summaryEl.textContent =
      `Saved ${s.saved}, duplicates ${s.duplicates}, failed ${s.failed}` +
      (s.cancelled ? `, cancelled ${s.cancelled}` : "");
    summaryEl.classList.remove("hidden");
  } else {
    setNotice((reply && reply.error) || "save failed", true);
  }
}

rescanBtn.addEventListener("click", rescan);
saveBtn.addEventListener("click", saveSelected);
cancelBtn.addEventListener("click", async () => {
  cancelBtn.disabled = true;
  await send({ type: "cancel_save" });
});

(async function init() {
  const bridge = await checkBridge();
  const tab = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab[0] || !/https:\/\/([^/]+\.)?tiktok\.com\//i.test(tab[0].url || "")) {
    setNotice("Open tiktok.com, enter a Direct Messages conversation, then " +
              "open this popup again.");
    return;
  }
  if (bridge && bridge.status !== "ok") {
    setNotice("Native bridge not connected — open Options and follow the " +
              "setup steps. Scanning still works; saving will not.", true);
  }
  await rescan();
})();
