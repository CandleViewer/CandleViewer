// E10-Q04 shell perf: what every browser and Electron bench boots the shell with (BQ-Q04-08, C-13.5):
// the signed-in owner's boot REST table, the web build's version, and the loopback-only network.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SETTINGS, sessionInfo } from "@candleviewer/fixtures/e2e/stubs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const WEB_ROOT = path.join(__dirname, "../../../../web/dist");

export const VERSION = (
  JSON.parse(readFileSync(path.join(__dirname, "../../../../web/package.json"), "utf8")) as {
    version: string;
  }
).version;

/** Name resolution fails for every host but loopback, from process start (before any route). */
export const RESOLVER =
  "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost";
/** Any http(s)/ws(s) URL whose host is not loopback; matched by Playwright, not per request in JS. */
export const NON_LOOPBACK =
  /^(?:https?|wss?):\/\/(?!(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?\/)/u;

/** The boot calls the shell makes for a signed-in owner (as `stubSession` answers them). */
export const REST: Readonly<Record<string, unknown>> = {
  "/api/v1/auth/refresh": {
    status: "authenticated",
    tokens: {
      access_token: ["perf", "stub", "opaque", "bearer"].join("."),
      token_type: "Bearer",
      expires_in: 600,
      refresh_expires_in: 2_592_000,
    },
  },
  "/api/v1/me": {
    role: "owner",
    permissions: [],
    session: { environment: "demo", elevated_until: null },
  },
  "/api/v1/me/preferences": {},
  "/api/v1/me/keymap": { bindings: [] },
  "/api/v1/settings": SETTINGS,
  "/api/v1/auth/session": sessionInfo("owner"),
  "/api/v1/health/live": { status: "ok" },
};
