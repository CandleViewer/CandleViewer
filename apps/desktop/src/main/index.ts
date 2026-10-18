import { app, BrowserWindow, ipcMain, protocol, session, shell } from "electron";
import type { IpcMainInvokeEvent } from "electron";
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
// build this is <resources>/web/dist, where electron-builder.yml copies it
// (see README "Load path").
const APP_ROOT_DIR = path.resolve(__dirname, "../../../web/dist");

// Electron requires custom schemes to be registered before the app is ready,
// and only once. The privileges are the closed set in appProtocol.ts.
protocol.registerSchemesAsPrivileged([{ scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES }]);

// No <webview> anywhere (SR-113): windows keep webviewTag off, and an attach that gets past
// that is refused here. Registered at load, before any web contents exists, so none escapes it.
app.on("web-contents-created", (_event, contents) => {
  contents.on("will-attach-webview", (event, _webPreferences, params) => {
    logAuditEvent("webview-denied", { url: safeOriginOf(params["src"] ?? "") });
    event.preventDefault();
  });
});

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
      // Unreachable for a value resolveDevServerUrl produced; kept so a forged one fails closed.
      return false;
    }
    return target.origin === dev.origin;
  }

  return isAppUrl(url);
}

/**
 * SR-111: true only for an IPC call from a window's main frame showing the shell's own page, by
 * the navigation rule above (app://candleviewer, or the accepted dev server's origin in an
 * unpackaged build). A sub-frame, another origin, about:blank, file: and an empty or unparseable
 * URL are refused.
 */
export function isTrustedIpcSender(
  frameUrl: string,
  isMainFrame: boolean,
  devServerUrl: DevServerUrl | undefined,
): boolean {
  return isMainFrame && isNavigationAllowed(frameUrl, devServerUrl);
}

/** What a refused IPC sender gets (SR-111): a fixed message, never data or the sender's URL. */
export class IpcSenderRefusedError extends Error {
  constructor() {
    super("IPC sender refused: not the shell's own page");
    this.name = "IpcSenderRefusedError";
  }
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
export function acceptedDevServerUrl(): DevServerUrl | undefined {
  const resolution = resolveDevServerUrl(process.env["CV_DEV_SERVER_URL"], app.isPackaged);
  if (resolution.kind === "ignored") {
    logAuditEvent("dev-server-url-ignored", { reason: resolution.reason });
  }
  return resolution.kind === "accepted" ? resolution.url : undefined;
}

export function createMainWindow(devServerUrl: DevServerUrl | undefined): BrowserWindow {
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
      webviewTag: false, // no <webview> (SR-113); an attach is refused for every web contents too
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

  // A redirect is a navigation the server picked, so the same rule applies (SR-113).
  win.webContents.on("will-redirect", (event, url) => {
    if (!isNavigationAllowed(url, devServerUrl)) {
      logAuditEvent("redirect-denied", { url: safeOriginOf(url) });
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

/** What the IPC sender check could read of the frame that sent a call. */
interface SenderFrame {
  readonly url: string;
  readonly kind: "main-frame" | "not-main-frame" | "frame-unavailable";
}

/**
 * Reads the sender frame's URL and whether it is the main frame of the web contents that sent the
 * call, by identity: the root of a nested frame tree has no parent either. No frame (navigated away
 * or destroyed) and a getter that throws (disposed mid-call) both mean the frame is unavailable.
 */
function readSenderFrame(event: IpcMainInvokeEvent): SenderFrame {
  try {
    const frame = event.senderFrame;
    if (frame === null) {
      return { url: "", kind: "frame-unavailable" };
    }
    const isMainFrame = frame === event.sender.mainFrame;
    return { url: frame.url, kind: isMainFrame ? "main-frame" : "not-main-frame" };
  } catch {
    return { url: "", kind: "frame-unavailable" };
  }
}

/**
 * Wraps an ipcMain.handle listener so it answers only the shell's own page (SR-111), checked
 * before `reply` runs; `reply` never sees the renderer's arguments. A refused call throws
 * IpcSenderRefusedError and logs one line: the reason and the sender's origin, never its URL.
 */
function fromShellPage<T>(
  devServerUrl: DevServerUrl | undefined,
  reply: () => T,
): (event: IpcMainInvokeEvent) => T {
  return (event) => {
    const { url, kind } = readSenderFrame(event);
    if (!isTrustedIpcSender(url, kind === "main-frame", devServerUrl)) {
      const reason = kind === "main-frame" ? "not-shell-origin" : kind;
      logAuditEvent("ipc-sender-refused", { reason, origin: safeOriginOf(url) });
      throw new IpcSenderRefusedError();
    }
    return reply();
  };
}

/** Registers the fixed set of ipcMain handlers backing the preload bridge (SR-111). */
function installIpcHandlers(devServerUrl: DevServerUrl | undefined): void {
  ipcMain.handle("cv:gpu:info", fromShellPage(devServerUrl, probeGpu));
  ipcMain.handle("cv:keychain:getKekHandle", fromShellPage(devServerUrl, getKekHandle));
  ipcMain.handle("cv:updates:check", fromShellPage(devServerUrl, checkForUpdate));
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
  // One dev-server decision per run, so the window's load, its guards and the IPC check agree.
  const devServerUrl = acceptedDevServerUrl();
  installCspHeader(csp);
  installAppProtocol(csp);
  installPermissionHandler();
  installIpcHandlers(devServerUrl);
  logStartup();
  createMainWindow(devServerUrl);
  app.emit("workspace-ready");
});
