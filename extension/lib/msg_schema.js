/* msg_schema.js — client-side validation of host commands.
 * Mirrors the native host's strict schema (tiktok_sticker_bridge.py) so bad
 * requests are caught before they ever reach the host. */
(function (global) {
  "use strict";

  const HOST_NAME = "com.tiktokstickers.bridge";

  const COMMANDS = {
    health_check: [],
    get_status: [],
    choose_output_folder: [],
    save_original: ["filename", "data_base64", "media_type", "sha256", "overwrite"],
  };

  /**
   * @param {{type: string}} cmd
   * @returns {{ok: boolean, error: string?}}
   */
  function validateHostCommand(cmd) {
    if (!cmd || typeof cmd !== "object" || Array.isArray(cmd)) {
      return { ok: false, error: "command must be an object" };
    }
    const type = cmd.type;
    if (typeof type !== "string" || !(type in COMMANDS)) {
      return { ok: false, error: `unsupported command: ${String(type)}` };
    }
    const allowed = new Set(["type", ...COMMANDS[type]]);
    for (const key of Object.keys(cmd)) {
      if (!allowed.has(key)) {
        return { ok: false, error: `unexpected field "${key}" for ${type}` };
      }
    }
    if (type === "save_original") {
      if (typeof cmd.filename !== "string" || !cmd.filename.trim()) {
        return { ok: false, error: "filename must be a non-empty string" };
      }
      if (typeof cmd.data_base64 !== "string" || cmd.data_base64.length === 0) {
        return { ok: false, error: "data_base64 must be a non-empty string" };
      }
      if (cmd.sha256 !== undefined && !/^[0-9a-fA-F]{64}$/.test(cmd.sha256)) {
        return { ok: false, error: "sha256 must be 64 hex characters" };
      }
      if (cmd.overwrite !== undefined && typeof cmd.overwrite !== "boolean") {
        return { ok: false, error: "overwrite must be boolean" };
      }
      if (cmd.media_type !== undefined && typeof cmd.media_type !== "string") {
        return { ok: false, error: "media_type must be a string" };
      }
    }
    return { ok: true };
  }

  const TT = (global.TT = global.TT || {});
  TT.Schema = { HOST_NAME, COMMANDS, validateHostCommand };
})(typeof globalThis !== "undefined" ? globalThis : self);
