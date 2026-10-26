/* sniff.js — magic-byte content classification (browser side).
 * Mirrors the native host's sniffing so the UI can label media accurately
 * before/after download. The host remains the final authority. */
(function (global) {
  "use strict";

  /**
   * @param {Uint8Array|ArrayBuffer} data
   * @returns {{mime: string, ext: string, animated: boolean, verified: boolean} | null}
   */
  function sniff(data) {
    const b = data instanceof Uint8Array ? data : new Uint8Array(data);
    if (b.length < 12) return null;
    const starts = (sig) => sig.every((v, i) => b[i] === v);
    const at = (off, sig) => sig.every((v, i) => b[off + i] === v);

    if (starts([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
      return { mime: "image/png", ext: "png", animated: false, verified: true };
    }
    if (starts([0x47, 0x49, 0x46, 0x38]) /* GIF8 */) {
      const head = new TextDecoder().decode(b.slice(0, 4096));
      return {
        mime: "image/gif", ext: "gif",
        animated: head.includes("NETSCAPE2.0"), verified: true,
      };
    }
    if (starts([0xff, 0xd8, 0xff])) {
      return { mime: "image/jpeg", ext: "jpg", animated: false, verified: true };
    }
    if (at(0, [0x52, 0x49, 0x46, 0x46]) && at(8, [0x57, 0x45, 0x42, 0x50])) {
      const vp8x = at(12, [0x56, 0x50, 0x38, 0x58]);
      const animFlag = vp8x && b.length > 20 && (b[20] & 0x02) !== 0;
      return { mime: "image/webp", ext: "webp", animated: animFlag, verified: true };
    }
    if (at(4, [0x66, 0x74, 0x79, 0x70]) /* ftyp */) {
      const brand = String.fromCharCode(b[8], b[9], b[10], b[11]);
      if (brand === "avif" || brand === "avis") {
        return { mime: "image/avif", ext: "avif", animated: brand === "avis", verified: true };
      }
      return { mime: "video/mp4", ext: "mp4", animated: true, verified: true };
    }
    if (starts([0x1a, 0x45, 0xdf, 0xa3])) {
      return { mime: "video/webm", ext: "webm", animated: true, verified: true };
    }
    return null;
  }

  const TT = (global.TT = global.TT || {});
  TT.Sniff = { sniff };
})(typeof globalThis !== "undefined" ? globalThis : self);
