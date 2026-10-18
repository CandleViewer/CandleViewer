import { app, BrowserWindow, ipcMain, protocol, session, shell } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HARDENED_WEB_PREFERENCES } from "./shellPort.js";
import { buildCsp } from "./csp.js";
import {
  APP_ENTRY_URL,
  APP_SCHEME,
  APP_SCHEME_PRIVILEGES,
  createDistReader,
  isAppUrl,
  resolveAppRequest,
} from "./appProtocol.js";
import { resolveDevServerUrl, type DevServerUrl } from "./devServer.js";
import { logStartup, logAuditEvent } from "./logger.js";
import { applyGpuFlags, probeGpu } from "./gpu.js";
import { getKekHandle } from "./keychain.js";
import { checkForUpdate } from "./updateChannel.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Single-instance lock: a second launch hands its args to the first
// instance and quits immediately rather than opening a second window (and a
// second, racing KEK-handle session).
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  // A second launch reaches here instead of quitting; focus (and restore, if
  // minimized) the existing window rather than leaving the user with no
  // visible window and no indication the app is already running.
  app.on("second-instance", () => {
    const [existing] = BrowserWindow.getAllWindows();
    if (existing) {
      if (existing.isMinimized()) {
        existing.restore();
      }
      existing.focus();
    }
  });
}

// The built web app (apps/web/dist), the only directory the app:// handler
// serves from (SR-174). Resolved once, relative to dist/main. In a packaged
// build this is <resources>/web/dist, which the installer does not ship yet
// (see README "Load path").
const APP_ROOT_DIR = path.resolve(__dirname, "../../../web/dist");

// Electron requires custom schemes to be registered before the app is ready,
// and only once. The privileges are the closed set in appProtocol.ts.
protocol.registerSchemesAsPrivileged([{ scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES }]);

/**
 * Returns the origin of `url` for audit logging, or "invalid-url" if it does
 * not parse. Never returns the full URL: query strings can carry tokens
 * (C-12.6) so only the origin is safe to persist. Node's URL reports origin
 * "null" for non-special schemes, so those log scheme and host (app:) or the
 * scheme alone when there is no host (file:, data:), never the path or query.
 */
export function safeOriginOf(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.origin !== "null") {
      return parsed.origin;
    }
    return parsed.host === "" ? parsed.protocol : `${parsed.protocol}//${parsed.host}`;
  } catch {
    return "invalid-url";
  }
}

/**
 * Returns true only if `url` is on the app origin: without a dev server, the
 * `app:` scheme with its one fixed host (served by the app:// handler); with
 * an accepted dev server (devServer.ts: unpackaged build, loopback http
 * only), exactly its origin. Compares parsed URL fields, never a string
 * prefix, so a lookalike host (e.g. "http://localhost:5173.evil.test")
 * cannot pass, and no `file:` URL is ever allowed.
 */
export function isNavigationAllowed(url: string, devServerUrl: DevServerUrl | undefined): boolean {
  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return false;
  }

  if (devServerUrl) {
    let dev: URL;
    try {
      dev = new URL(devServerUrl);
    } catch {
      return false;
    }
    return target.origin === dev.origin;
  }

  return isAppUrl(url);
}

/**
 * Scheme `shell.openExternal` is allowed to hand off to the OS browser
 * (SR-113): only `https:` — plain `http:` is never handed to the OS shell
 * (no integrity/confidentiality on the wire, and it is not needed by any
 * genuine external destination this app links to), and no arbitrary scheme
 * (e.g. `file:`, a custom protocol, or something that could trigger a local
 * application handler unexpectedly).
 */
const ALLOWED_EXTERNAL_PROTOCOLS = new Set(["https:"]);

/**
 * Hosts `shell.openExternal` is allowed to hand off to the OS browser
 * (SR-113 requires scheme **and** host). Scheme-only checks let a
 * compromised/malicious renderer send the user's OS browser to an arbitrary
 * attacker-controlled `https:` URL (phishing, credential harvesting); this
 * closed allowlist limits external hand-off to CandleViewer's own docs host
 * and the exchange this product integrates with. Extend deliberately, in
 * review, not via runtime configuration.
 */
const ALLOWED_EXTERNAL_HOSTS = new Set(["docs.candleviewer.app", "www.bybit.com", "bybit.com"]);

/**
 * Returns true only if `url` is `https:` and its host is on the fixed
 * allowlist, and it is not the app's own dev server or packaged origin —
 * i.e. it is a genuine, known external link, not a same-origin navigation
 * that merely used `window.open`.
 */
export function isExternalLinkAllowed(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return (
    ALLOWED_EXTERNAL_PROTOCOLS.has(parsed.protocol) && ALLOWED_EXTERNAL_HOSTS.has(parsed.hostname)
  );
}

/**
 * The dev server the main window may load (#3411), or undefined for the
 * shell's own bundle. A set value the shell does not honour is logged by
 * reason only, never echoed: it may carry anything (C-12.6).
 */
function acceptedDevServerUrl(): DevServerUrl | undefined {
  const resolution = resolveDevServerUrl(process.env["CV_DEV_SERVER_URL"], app.isPackaged);
  if (resolution.kind === "ignored") {
    logAuditEvent("dev-server-url-ignored", { reason: resolution.reason });
  }
  return resolution.kind === "accepted" ? resolution.url : undefined;
}

export function createMainWindow(): BrowserWindow {
  // Decided once per window, so the load and both navigation guards agree.
  const devServerUrl = acceptedDevServerUrl();
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: HARDENED_WEB_PREFERENCES.contextIsolation,
      nodeIntegration: HARDENED_WEB_PREFERENCES.nodeIntegration,
      nodeIntegrationInWorker: HARDENED_WEB_PREFERENCES.nodeIntegrationInWorker,
      nodeIntegrationInSubFrames: HARDENED_WEB_PREFERENCES.nodeIntegrationInSubFrames,
      sandbox: HARDENED_WEB_PREFERENCES.sandbox,
      webSecurity: HARDENED_WEB_PREFERENCES.webSecurity,
      allowRunningInsecureContent: HARDENED_WEB_PREFERENCES.allowRunningInsecureContent,
      experimentalFeatures: HARDENED_WEB_PREFERENCES.experimentalFeatures,
      // enableRemoteModule is deliberately absent (SR-110) — never set it.
    },
  });

  // "shell interactive" instrumentation (Performance notes): the window is
  // created hidden and shown only on first paint to avoid a white flash and
  // to keep the measured cold-start honest (budget #10, <=3s cold start).
  win.once("ready-to-show", () => {
    win.show();
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isExternalLinkAllowed(url) && !isNavigationAllowed(url, devServerUrl)) {
      logAuditEvent("external-link-opened", { url: safeOriginOf(url) });
      void shell.openExternal(url);
    } else {
      logAuditEvent("window-open-denied", { url: safeOriginOf(url) });
    }
    return { action: "deny" };
  });

  win.webContents.on("will-navigate", (event, url) => {
    if (!isNavigationAllowed(url, devServerUrl)) {
      logAuditEvent("navigation-denied", { url: safeOriginOf(url) });
      event.preventDefault();
    }
  });

  void win.loadURL(devServerUrl ?? APP_ENTRY_URL);

  return win;
}

function installCspHeader(csp: string): void {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    // The app:// handler answers every app: request (any host) with this
    // header already; leave those unchanged: one CSP source, never two.
    if (details.url.startsWith(`${APP_SCHEME}:`)) {
      callback({});
      return;
    }
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [csp],
      },
    });
  });
}

/**
 * Serves the built web app over app:// (SR-174): a read-only static-file
 * handler confined to APP_ROOT_DIR that attaches the shell's CSP header
 * (SR-112) to every response it returns.
 */
function installAppProtocol(csp: string): void {
  const read = createDistReader(APP_ROOT_DIR);
  protocol.handle(APP_SCHEME, async (request) => {
    const { url, method } = request;
    const response = await resolveAppRequest(url, APP_ROOT_DIR, read, csp, method);
    return new Response(response.body, { status: response.status, headers: response.headers });
  });
}

/**
 * Denies every Electron permission the app does not need. Nothing in
 * CandleViewer's scope needs camera, microphone, geolocation, MIDI or OS
 * notifications from the renderer's own request path (notifications are
 * surfaced via `ShellPort.notifications`, main-process initiated) — every
 * request is therefore explicitly denied rather than left to Electron's
 * default (which varies by permission).
 */
function installPermissionHandler(): void {
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });
}

/** Registers the fixed set of ipcMain handlers backing the preload bridge (SR-111). */
function installIpcHandlers(): void {
  ipcMain.handle("cv:gpu:info", () => probeGpu());
  ipcMain.handle("cv:keychain:getKekHandle", () => getKekHandle());
  ipcMain.handle("cv:updates:check", () => checkForUpdate());
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

// GPU flags must be applied before app.whenReady() (Electron requirement);
// see GPU_FLAGS.md for the documented rationale of each switch.
applyGpuFlags();

void app.whenReady().then(() => {
  // One CSP value for both delivery points: the dev-server response hook and
  // the app:// handler.
  const csp = buildCsp();
  installCspHeader(csp);
  installAppProtocol(csp);
  installPermissionHandler();
  installIpcHandlers();
  logStartup();
  createMainWindow();
  app.emit("workspace-ready");
});
