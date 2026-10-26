/* tests.js — unit tests for the extension's pure-logic libraries.
 * Runs in any browser context (headless Chrome via tests/run_js_tests.py).
 * The runner page provides #results where the summary JSON is written. */
"use strict";

(function () {
  const results = { pass: 0, fail: 0, failures: [] };

  function test(name, fn) {
    try {
      fn();
      results.pass++;
    } catch (e) {
      results.fail++;
      results.failures.push({ name, error: String(e && e.message || e) });
    }
  }

  function assert(cond, msg) {
    if (!cond) throw new Error(msg || "assertion failed");
  }

  function assertEq(actual, expected, msg) {
    const a = JSON.stringify(actual);
    const b = JSON.stringify(expected);
    if (a !== b) throw new Error(`${msg || "not equal"}: ${a} != ${b}`);
  }

  function bytes(arr) { return new Uint8Array(arr); }

  /* ---------------- TT.Sniff ---------------- */

  test("sniff png", () => {
    const r = TT.Sniff.sniff(bytes([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a, 0,1,2,3, 4,5,6,7]));
    assertEq([r.mime, r.ext, r.animated, r.verified],
             ["image/png", "png", false, true]);
  });

  test("sniff static gif", () => {
    const head = [0x47,0x49,0x46,0x38,0x39,0x61, 1,0, 1,0, 0, 0];
    const r = TT.Sniff.sniff(bytes(head.concat(new Array(40).fill(0))));
    assertEq([r.mime, r.animated], ["image/gif", false]);
  });

  test("sniff animated gif", () => {
    const head = [0x47,0x49,0x46,0x38,0x39,0x61, 1,0, 1,0, 0, 0];
    const netscape = [..."NETSCAPE2.0"].map((c) => c.charCodeAt(0));
    const r = TT.Sniff.sniff(bytes(head.concat(netscape, new Array(20).fill(0))));
    assertEq([r.mime, r.animated], ["image/gif", true]);
  });

  test("sniff jpeg", () => {
    const r = TT.Sniff.sniff(bytes([0xff,0xd8,0xff,0xe0, 0,0,0,0, 0,0,0,0, 0,0,0,0]));
    assertEq([r.mime, r.ext], ["image/jpeg", "jpg"]);
  });

  test("sniff static webp", () => {
    const riff = [..."RIFF"].map((c) => c.charCodeAt(0));
    const webp = [..."WEBP"].map((c) => c.charCodeAt(0));
    const vp8 = [..."VP8 "].map((c) => c.charCodeAt(0));
    const r = TT.Sniff.sniff(bytes(riff.concat([0,0,0,0], webp, vp8, [0,0,0,0], [0,0,0,0])));
    assertEq([r.mime, r.ext, r.animated], ["image/webp", "webp", false]);
  });

  test("sniff animated webp (VP8X animation bit)", () => {
    const riff = [..."RIFF"].map((c) => c.charCodeAt(0));
    const webp = [..."WEBP"].map((c) => c.charCodeAt(0));
    const vp8x = [..."VP8X"].map((c) => c.charCodeAt(0));
    const r = TT.Sniff.sniff(bytes(riff.concat([0,0,0,0], webp, vp8x, [0,0,0,0], [0x02], [0,0,0,0], [0,0,0,0])));
    assertEq([r.mime, r.ext, r.animated], ["image/webp", "webp", true]);
  });

  test("sniff mp4", () => {
    const ftyp = [..."ftyp"].map((c) => c.charCodeAt(0));
    const brand = [..."M4V "].map((c) => c.charCodeAt(0));
    const r = TT.Sniff.sniff(bytes([0, 0, 0, 0x18].concat(ftyp, brand, new Array(8).fill(0))));
    assertEq([r.mime, r.ext, r.animated], ["video/mp4", "mp4", true]);
  });

  test("sniff webm", () => {
    const r = TT.Sniff.sniff(bytes([0x1a,0x45,0xdf,0xa3, 0,0,0,0, 0,0,0,0, 0,0,0,0]));
    assertEq([r.mime, r.ext], ["video/webm", "webm"]);
  });

  test("sniff unknown and short payloads", () => {
    assertEq(TT.Sniff.sniff(bytes([..."not a media file!!"])), null);
    assertEq(TT.Sniff.sniff(bytes([1, 2, 3])), null);
  });

  /* ---------------- TT.Detect ---------------- */

  test("isMediaUrl accepts DM sticker host pattern", () => {
    const url = "https://p16-tiktok-dm-sticker-sign-useast2a.ibyteimg.com/tos-alisg/sticker.webp";
    assert(TT.Detect.isMediaUrl(url), "should match sticker host");
  });

  test("isMediaUrl accepts configurable pattern (tplv-dhq)", () => {
    const url = "https://sf16-website-login.neutral.ttwstatic.com/tplv-dhq/x.webp";
    assert(TT.Detect.isMediaUrl(url), "should match tplv-dhq on ttwstatic");
  });

  test("isMediaUrl rejects foreign hosts", () => {
    assert(!TT.Detect.isMediaUrl("https://evil.example.com/tiktok-dm-sticker/a.webp"));
    assert(!TT.Detect.isMediaUrl("https://www.ibyteimg.com/random/preview.png"),
           "pattern-less URL must not match");
  });

  test("isMediaUrl rejects non-http schemes", () => {
    assert(!TT.Detect.isMediaUrl("chrome-extension://abc/manifest.json"));
    assert(!TT.Detect.isMediaUrl("file:///x/sticker.webp"));
  });

  test("classifyUrl animated hint", () => {
    assertEq(TT.Detect.classifyUrl("https://x.tiktokcdn.com/video2sticker/abc"),
             { kind: "sticker", animated: true, label: "sticker (animated, URL hint)" });
  });

  test("classifyUrl photo-comment", () => {
    const r = TT.Detect.classifyUrl("https://x.ibyteimg.com/photo-comment/abc.webp");
    assertEq([r.kind, r.animated], ["photo", false]);
  });

  test("suggestFilename strips tplv transform suffix", () => {
    // The transform suffix carries no trustworthy extension, so the
    // suggestion drops it; the native host re-derives the extension from
    // actual content bytes anyway.
    assertEq(TT.Detect.suggestFilename(
      "https://p16-ibyteimg.com/img/sticker01~tplv-dhq-x.webp"),
      "sticker01");
  });

  test("suggestFilename maps awebp to webp", () => {
    assertEq(TT.Detect.suggestFilename(
      "https://x.tiktokcdn.com/sticker.awebp"), "sticker.webp");
  });

  test("suggestFilename sanitizes unsafe characters", () => {
    assertEq(TT.Detect.suggestFilename(
      'https://x.tiktokcdn.com/a<b>:c"d.webp'), "a_b__c_d.webp");
  });

  test("suggestFilename falls back when no name", () => {
    assertEq(TT.Detect.suggestFilename("https://x.tiktokcdn.com/"),
             "tiktok-media");
  });

  test("imgCandidateUrls parses src, currentSrc and srcset", () => {
    const img = document.createElement("img");
    img.src = "https://x.ibyteimg.com/a.webp";
    img.setAttribute("srcset",
      "https://x.ibyteimg.com/a-small.webp 1x, https://x.ibyteimg.com/a-big.webp 2x");
    const urls = TT.Detect.imgCandidateUrls(img);
    assert(urls.includes("https://x.ibyteimg.com/a.webp"));
    assert(urls.includes("https://x.ibyteimg.com/a-small.webp"));
    assert(urls.includes("https://x.ibyteimg.com/a-big.webp"));
    assertEq(urls.length, 3);
  });

  test("backgroundUrls parses css url() values", () => {
    const urls = TT.Detect.backgroundUrls(
      'url("https://x.ibyteimg.com/bg.webp") no-repeat, url(https://x.ibyteimg.com/bg2.webp)');
    assertEq(urls, ["https://x.ibyteimg.com/bg.webp",
                    "https://x.ibyteimg.com/bg2.webp"]);
    assertEq(TT.Detect.backgroundUrls("none"), []);
  });

  test("hostAllowed matches exact and subdomains only", () => {
    assert(TT.Detect.hostAllowed("p16-sign-va.tiktokcdn.com", ["tiktokcdn.com"]));
    assert(TT.Detect.hostAllowed("tiktokcdn.com", ["tiktokcdn.com"]));
    assert(!TT.Detect.hostAllowed("eviltiktokcdn.com", ["tiktokcdn.com"]));
  });

  /* ---------------- TT.Schema ---------------- */

  test("schema accepts valid save_original", () => {
    const cmd = { type: "save_original", filename: "a.webp",
                  data_base64: "AAAA", sha256: "ab".repeat(64 / 2),
                  overwrite: false, media_type: "image/webp" };
    assert(TT.Schema.validateHostCommand(cmd).ok);
  });

  test("schema rejects unknown command and fields", () => {
    assert(!TT.Schema.validateHostCommand({ type: "run_shell" }).ok);
    assert(!TT.Schema.validateHostCommand({ type: "health_check", x: 1 }).ok);
    assert(!TT.Schema.validateHostCommand({ type: "save_original", filename: "a" }).ok);
    assert(!TT.Schema.validateHostCommand(null).ok);
  });

  test("schema rejects bad sha256 and bad types", () => {
    assert(!TT.Schema.validateHostCommand(
      { type: "save_original", filename: "a", data_base64: "AA", sha256: "zz" }).ok);
    assert(!TT.Schema.validateHostCommand(
      { type: "save_original", filename: "", data_base64: "AA" }).ok);
    assert(!TT.Schema.validateHostCommand(
      { type: "save_original", filename: "a", data_base64: 5 }).ok);
  });

  test("host name is the registered bridge name", () => {
    assertEq(TT.Schema.HOST_NAME, "com.tiktokstickers.bridge");
  });

  /* ---------------- report ---------------- */

  const out = document.getElementById("results");
  out.textContent = "__TTSTK_RESULTS__" + JSON.stringify(results);
})();
