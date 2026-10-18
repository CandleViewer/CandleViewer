import { afterEach, beforeAll, describe, expect, it, vi, type Mock } from "vitest";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { app, BrowserWindow, ipcMain, protocol, session, type IpcMainInvokeEvent } from "electron";
import { buildCsp } from "../src/main/csp";
import { resolveDevServerUrl, type DevServerUrl } from "../src/main/devServer";
import { logAuditEvent } from "../src/main/logger";

// src/main/index.ts calls app.on(...) / app.whenReady() at module scope, so
// the real "electron" module (unavailable under vitest's node environment)
// must be mocked before the module under test is imported.
vi.mock("electron", () => ({
  app: {
    on: vi.fn(),
    whenReady: vi.fn().mockResolvedValue(undefined),
    getVersion: vi.fn().mockReturnValue("0.0.0"),
    getPath: vi.fn().mockReturnValue("/tmp"),
    getGPUInfo: vi.fn().mockResolvedValue({}),
    emit: vi.fn(),
    requestSingleInstanceLock: vi.fn().mockReturnValue(true),
    quit: vi.fn(),
    commandLine: { appendSwitch: vi.fn() },
    isPackaged: false,
  },
  BrowserWindow: vi.fn().mockImplementation(() => ({
    webContents: {
      setWindowOpenHandler: vi.fn(),
      on: vi.fn(),
    },
    once: vi.fn(),
    show: vi.fn(),
    loadURL: vi.fn(),
    loadFile: vi.fn(),
  })),
  session: {
    defaultSession: {
      webRequest: { onHeadersReceived: vi.fn() },
      setPermissionRequestHandler: vi.fn(),
    },
  },
  ipcMain: { handle: vi.fn() },
  protocol: { registerSchemesAsPrivileged: vi.fn(), handle: vi.fn() },
  shell: { openExternal: vi.fn() },
}));

// Captures the shell's log lines in memory; the real logger appends to a file in userData.
vi.mock("../src/main/logger", () => ({ logStartup: vi.fn(), logAuditEvent: vi.fn() }));

// The default load path is under test: no dev server.
delete process.env["CV_DEV_SERVER_URL"];

const {
  isNavigationAllowed,
  safeOriginOf,
  isExternalLinkAllowed,
  createMainWindow,
  acceptedDevServerUrl,
  isTrustedIpcSender,
  IpcSenderRefusedError,
} = await import("../src/main/index");

/** A dev-server URL the shell accepted: the only kind isNavigationAllowed takes. */
function acceptedDevUrl(raw: string): DevServerUrl {
  const resolution = resolveDevServerUrl(raw, false);
  if (resolution.kind !== "accepted") {
    throw new Error(`${raw} is not an accepted dev-server URL`);
  }
  return resolution.url;
}

const DEV = acceptedDevUrl("http://localhost:5173");

const APP_ROOT = path.resolve(
  process.platform === "win32" ? "C:\\app\\web\\dist" : "/app/web/dist",
);

describe("isNavigationAllowed", () => {
  it("allows the app origin and its client routes when there is no dev server", () => {
    expect(isNavigationAllowed("app://candleviewer/", undefined)).toBe(true);
    expect(isNavigationAllowed("app://candleviewer/login?next=%2Fterminal", undefined)).toBe(true);
  });

  it("denies a file:// URL, even one inside the real web dist root that index.ts serves", () => {
    const webDist = path.resolve(import.meta.dirname, "../../web/dist"); // index.ts APP_ROOT_DIR
    const url = pathToFileURL(path.join(webDist, "index.html")).href;
    expect(isNavigationAllowed(url, undefined)).toBe(false);
    const outside = pathToFileURL(path.resolve(APP_ROOT, "..", "..", "secrets.txt")).href;
    expect(isNavigationAllowed(outside, undefined)).toBe(false);
  });

  it("denies another host, a port or credentials on the app scheme", () => {
    expect(isNavigationAllowed("app://evil.test/", undefined)).toBe(false);
    expect(isNavigationAllowed("app://candleviewer:8080/", undefined)).toBe(false);
    expect(isNavigationAllowed("app://user@candleviewer/", undefined)).toBe(false);
  });

  it("denies non-app navigation when there is no dev server", () => {
    expect(isNavigationAllowed("https://example.com", undefined)).toBe(false);
  });

  it("allows navigation to exactly the dev server origin", () => {
    expect(isNavigationAllowed("http://localhost:5173/", DEV)).toBe(true);
    expect(isNavigationAllowed("http://localhost:5173/route", DEV)).toBe(true);
  });

  it("denies a lookalike host that merely starts with the dev origin string", () => {
    expect(isNavigationAllowed("http://localhost:5173.evil.test/", DEV)).toBe(false);
  });

  it("denies a different scheme or port than the dev server", () => {
    expect(isNavigationAllowed("https://localhost:5173/", DEV)).toBe(false);
    expect(isNavigationAllowed("http://localhost:9999/", DEV)).toBe(false);
  });

  it("denies the app origin while a dev server is configured", () => {
    expect(isNavigationAllowed("app://candleviewer/", DEV)).toBe(false);
  });

  it("denies an unparseable URL", () => {
    expect(isNavigationAllowed("not a url", undefined)).toBe(false);
  });
});

describe("safeOriginOf", () => {
  it("returns only the origin, dropping any query string / token", () => {
    expect(safeOriginOf("https://example.com/path?token=secret")).toBe("https://example.com");
  });

  it("logs scheme and host for an app: URL, without its path or query", () => {
    expect(safeOriginOf("app://candleviewer/login?token=secret")).toBe("app://candleviewer");
  });

  it("logs only the scheme for a URL without a host, never the path", () => {
    expect(safeOriginOf("file:///home/user/secrets.txt")).toBe("file:");
    expect(safeOriginOf("data:text/html,<p>secret</p>")).toBe("data:");
  });

  it("returns a fixed placeholder for an unparseable URL instead of throwing", () => {
    expect(safeOriginOf("not a url")).toBe("invalid-url");
  });
});

describe("app:// wiring (#3410)", () => {
  it("registers only the app scheme, as standard and secure, before ready", () => {
    expect(protocol.registerSchemesAsPrivileged).toHaveBeenCalledTimes(1);
    expect(protocol.registerSchemesAsPrivileged).toHaveBeenCalledWith([
      { scheme: "app", privileges: { standard: true, secure: true } },
    ]);
  });

  it("loads the main window from app:// when no dev server is set, never from a file", async () => {
    await vi.waitFor(() => expect(BrowserWindow).toHaveBeenCalled());
    const win = vi.mocked(BrowserWindow).mock.results[0]?.value as {
      loadURL: ReturnType<typeof vi.fn>;
      loadFile: ReturnType<typeof vi.fn>;
    };
    expect(win.loadURL).toHaveBeenCalledWith("app://candleviewer/");
    expect(win.loadFile).not.toHaveBeenCalled();
  });

  it("the app:// handler adds the CSP, refuses other hosts and non-GET methods", async () => {
    await vi.waitFor(() => expect(protocol.handle).toHaveBeenCalled());
    const [scheme, handler] = vi.mocked(protocol.handle).mock.calls[0] ?? [];
    expect(scheme).toBe("app");
    if (handler === undefined) {
      throw new Error("no app:// handler registered");
    }
    const response = await handler(new Request("app://evil.test/index.html"));
    expect(response.status).toBe(404);
    expect(response.headers.get("content-security-policy")).toBe(buildCsp());
    const post = await handler(new Request("app://candleviewer/", { method: "POST" }));
    expect(post.status).toBe(405);
  });

  it("the response hook leaves app:// responses to the handler and adds the CSP to others", async () => {
    const hook = vi.mocked(session.defaultSession.webRequest.onHeadersReceived);
    await vi.waitFor(() => expect(hook).toHaveBeenCalled());
    const listener = hook.mock.calls[0]?.[0];
    if (typeof listener !== "function") {
      throw new Error("no onHeadersReceived listener registered");
    }
    const details = (url: string): Parameters<typeof listener>[0] =>
      ({ url, responseHeaders: { "x-a": ["b"] } }) as unknown as Parameters<typeof listener>[0];

    const appCallback = vi.fn();
    listener(details("app://candleviewer/"), appCallback);
    listener(details("app://other.test/missing.js"), appCallback); // the handler's 404, any host
    expect(appCallback.mock.calls).toEqual([[{}], [{}]]);

    const devCallback = vi.fn();
    listener(details("http://127.0.0.1:5173/"), devCallback);
    expect(devCallback).toHaveBeenCalledWith({
      responseHeaders: { "x-a": ["b"], "Content-Security-Policy": [buildCsp()] },
    });
  });
});

interface MockWindow {
  readonly webContents: { readonly on: Mock };
  readonly loadURL: Mock;
}

type NavigateListener = (event: { preventDefault: () => void }, url: string) => void;

/** The window `createMainWindow(devServerUrl)` built. */
function openWindow(devServerUrl: DevServerUrl | undefined): MockWindow {
  createMainWindow(devServerUrl);
  return vi.mocked(BrowserWindow).mock.results.at(-1)?.value as MockWindow;
}

/** True when the window's `name` guard lets `url` through (it did not call preventDefault). */
function passes(win: MockWindow, name: "will-navigate" | "will-redirect", url: string): boolean {
  const listener = win.webContents.on.mock.calls.find(([event]) => event === name)?.[1];
  if (typeof listener !== "function") {
    throw new Error(`no ${name} listener registered`);
  }
  const event = { preventDefault: vi.fn() };
  (listener as NavigateListener)(event, url);
  return event.preventDefault.mock.calls.length === 0;
}

describe("CV_DEV_SERVER_URL in the main window (#3411)", () => {
  afterEach(() => {
    delete process.env["CV_DEV_SERVER_URL"];
    Object.assign(app, { isPackaged: false });
  });

  /** Opens a main window with `raw` set; reports what it loaded, what it logged, and its guards. */
  function openMainWindow(raw: string, isPackaged: boolean) {
    process.env["CV_DEV_SERVER_URL"] = raw;
    Object.assign(app, { isPackaged });
    vi.mocked(logAuditEvent).mockClear();
    const win = openWindow(acceptedDevServerUrl());
    const logs = [...vi.mocked(logAuditEvent).mock.calls];
    return {
      loaded: win.loadURL.mock.calls[0]?.[0] as unknown,
      logs,
      navigates: (url: string) => passes(win, "will-navigate", url),
      redirects: (url: string) => passes(win, "will-redirect", url),
    };
  }

  it("loads an accepted loopback dev server and allows navigation on its origin only", () => {
    const win = openMainWindow("http://127.0.0.1:4173", false);
    expect(win.loaded).toBe("http://127.0.0.1:4173/");
    expect(win.logs).toEqual([]);
    expect(win.navigates("http://127.0.0.1:4173/terminal")).toBe(true);
    expect(win.navigates("http://localhost:4173/")).toBe(false);
    expect(win.navigates("app://candleviewer/")).toBe(false);
    expect(win.redirects("http://127.0.0.1:4173/login")).toBe(true);
    expect(win.redirects("https://evil.test/")).toBe(false);
    expect(win.redirects("app://candleviewer/")).toBe(false);
  });

  it.each([
    ["http://example.test:4173", false, "not-loopback-http"],
    ["https://127.0.0.1:4173", false, "not-loopback-http"],
    ["http://127.0.0.1", false, "malformed"],
    ["http://127.0.0.1:4173", true, "unpackaged-only"],
  ] as const)(
    "ignores %s (packaged: %s): loads app://, logs %s only",
    (raw, isPackaged, reason) => {
      const win = openMainWindow(raw, isPackaged);
      expect(win.loaded).toBe("app://candleviewer/");
      expect(win.logs).toEqual([["dev-server-url-ignored", { reason }]]);
      expect(JSON.stringify(win.logs)).not.toContain(raw);
      expect(win.navigates(`${new URL(raw).origin}/`)).toBe(false);
      expect(win.navigates("app://candleviewer/terminal")).toBe(true);
      expect(win.redirects(`${new URL(raw).origin}/`)).toBe(false);
      expect(win.redirects("app://candleviewer/terminal")).toBe(true);
    },
  );

  it("a packaged build never trusts an IPC call from the dev origin (#3608)", () => {
    process.env["CV_DEV_SERVER_URL"] = "http://localhost:5173";
    Object.assign(app, { isPackaged: true });
    const decision = acceptedDevServerUrl();
    expect(decision).toBeUndefined();
    expect(isTrustedIpcSender("http://localhost:5173/", true, decision)).toBe(false);
    expect(isTrustedIpcSender("app://candleviewer/", true, decision)).toBe(true);
  });
});

describe("isExternalLinkAllowed (SR-113)", () => {
  it("allows an https URL on the host allowlist", () => {
    expect(isExternalLinkAllowed("https://docs.candleviewer.app/guide")).toBe(true);
    expect(isExternalLinkAllowed("https://www.bybit.com/en/help")).toBe(true);
    expect(isExternalLinkAllowed("https://bybit.com/en/help")).toBe(true);
  });

  it("denies an http URL even for an allowlisted host", () => {
    expect(isExternalLinkAllowed("http://docs.candleviewer.app")).toBe(false);
  });

  it("denies an https URL for a host not on the allowlist", () => {
    expect(isExternalLinkAllowed("https://example.com")).toBe(false);
  });

  it("denies a lookalike host that merely contains an allowlisted host", () => {
    expect(isExternalLinkAllowed("https://docs.candleviewer.app.evil.test")).toBe(false);
    expect(isExternalLinkAllowed("https://evil-bybit.com")).toBe(false);
  });

  it("denies a file:// URL", () => {
    expect(isExternalLinkAllowed("file:///etc/passwd")).toBe(false);
  });

  it("denies a custom-protocol URL", () => {
    expect(isExternalLinkAllowed("app://internal-action")).toBe(false);
  });

  it("denies an unparseable URL", () => {
    expect(isExternalLinkAllowed("not a url")).toBe(false);
  });
});

describe("redirects and <webview> (SR-113, #3608)", () => {
  it("refuses a redirect off the app origin, logging its origin only; one on it passes", () => {
    const win = openWindow(undefined);
    vi.mocked(logAuditEvent).mockClear();
    expect(passes(win, "will-redirect", "https://evil.test/phish?token=secret")).toBe(false);
    expect(passes(win, "will-redirect", "http://localhost:5173/")).toBe(false);
    expect(passes(win, "will-redirect", "file:///etc/hosts")).toBe(false);
    expect(passes(win, "will-redirect", "app://candleviewer/terminal?tab=1")).toBe(true);
    expect(vi.mocked(logAuditEvent).mock.calls).toEqual([
      ["redirect-denied", { url: "https://evil.test" }],
      ["redirect-denied", { url: "http://localhost:5173" }],
      ["redirect-denied", { url: "file:" }],
    ]);
  });

  it("keeps webviewTag off in the window's webPreferences", () => {
    openWindow(undefined);
    const options = vi.mocked(BrowserWindow).mock.calls.at(-1)?.[0];
    expect(options?.webPreferences?.webviewTag).toBe(false);
  });

  it("denies a <webview> attachment in every web contents, logging its origin only", () => {
    type Listener = (...args: unknown[]) => void;
    const created = (app.on as unknown as Mock).mock.calls.find(
      ([name]) => name === "web-contents-created",
    );
    const contents = { on: vi.fn() };
    (created?.[1] as Listener)({}, contents);
    const attach = contents.on.mock.calls.find(([name]) => name === "will-attach-webview");
    vi.mocked(logAuditEvent).mockClear();
    const event = { preventDefault: vi.fn() };
    (attach?.[1] as Listener)(event, {}, { src: "https://evil.test/x?token=secret" });
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(vi.mocked(logAuditEvent).mock.calls).toEqual([
      ["webview-denied", { url: "https://evil.test" }],
    ]);
  });
});

type IpcListener = (event: IpcMainInvokeEvent) => unknown;

const IPC_CHANNELS = ["cv:gpu:info", "cv:keychain:getKekHandle", "cv:updates:check"] as const;

/** The listener the shell registered for `channel` at startup (no dev server set). */
function ipcListener(channel: string): IpcListener {
  const listener = vi.mocked(ipcMain.handle).mock.calls.find(([name]) => name === channel)?.[1];
  if (listener === undefined) {
    throw new Error(`no ipcMain handler for ${channel}`);
  }
  return listener as IpcListener;
}

type SenderFrame = "main" | "sub" | "nested-root" | "none";

/**
 * An invoke event from `url` in the main frame, or in a sub-frame, the root of a nested frame tree
 * (no parent either) or no frame, while the web contents' main frame is on the shell page.
 */
function invokeFrom(url: string, frame: SenderFrame): IpcMainInvokeEvent {
  const mainFrame = { url: frame === "main" ? url : "app://candleviewer/", parent: null };
  const senderFrame = {
    main: mainFrame,
    sub: { url, parent: mainFrame },
    "nested-root": { url, parent: null },
    none: null,
  }[frame];
  return { senderFrame, sender: { mainFrame } } as unknown as IpcMainInvokeEvent;
}

/** An invoke event from the app origin's main frame where reading `part` throws (disposed). */
function invokeDisposed(part: "senderFrame" | "url" | "mainFrame"): IpcMainInvokeEvent {
  const gone = (): never => {
    throw new Error("Render frame was disposed before WebFrameMain could be accessed");
  };
  const frame = { url: "app://candleviewer/", parent: null };
  const event = { senderFrame: frame, sender: { mainFrame: frame } };
  const owner = { senderFrame: event, url: frame, mainFrame: event.sender }[part];
  Object.defineProperty(owner, part, { get: gone });
  return event as unknown as IpcMainInvokeEvent;
}

describe("ipcMain handlers answer only the shell's own page (SR-111, #3608)", () => {
  beforeAll(async () => {
    await vi.waitFor(() => expect(ipcMain.handle).toHaveBeenCalledTimes(IPC_CHANNELS.length));
  });

  it("isTrustedIpcSender: a main frame on the app origin, or an accepted dev server's only", () => {
    expect(isTrustedIpcSender("app://candleviewer/terminal", true, undefined)).toBe(true);
    expect(isTrustedIpcSender("http://localhost:5173/terminal", true, DEV)).toBe(true);
    expect(isTrustedIpcSender("app://candleviewer/", true, DEV)).toBe(false);
    expect(isTrustedIpcSender("http://localhost:5174/", true, DEV)).toBe(false);
    expect(isTrustedIpcSender("http://localhost:5173/", false, DEV)).toBe(false);
    expect(isTrustedIpcSender("app://candleviewer/", false, undefined)).toBe(false);
  });

  it("answers every channel for the app origin's main frame", async () => {
    const from = invokeFrom("app://candleviewer/terminal?tab=1", "main");
    await expect(ipcListener("cv:gpu:info")(from)).resolves.toMatchObject({ vendor: "unknown" });
    expect(ipcListener("cv:keychain:getKekHandle")(from)).toMatch(/^kek-handle-/);
    expect(ipcListener("cv:updates:check")(from)).toEqual({
      state: "error",
      reason: "UPDATE_CHANNEL_DISABLED",
    });
  });

  it.each([
    ["https://evil.test/x?token=secret", "main", "not-shell-origin", "https://evil.test"],
    ["http://localhost:5173/", "main", "not-shell-origin", "http://localhost:5173"],
    ["app://candleviewer.evil.test/", "main", "not-shell-origin", "app://candleviewer.evil.test"],
    ["about:blank", "main", "not-shell-origin", "about:"],
    ["file:///app/web/dist/index.html", "main", "not-shell-origin", "file:"],
    ["", "main", "not-shell-origin", "invalid-url"],
    ["app://candleviewer/", "sub", "not-main-frame", "app://candleviewer"],
    ["https://evil.test/ad?token=secret", "sub", "not-main-frame", "https://evil.test"],
    ["app://candleviewer/", "nested-root", "not-main-frame", "app://candleviewer"],
    ["", "none", "frame-unavailable", "invalid-url"],
  ] as const)("refuses %j from a %s frame (%s), logged once", (url, frame, reason, origin) => {
    vi.mocked(app.getGPUInfo).mockClear();
    // Every registered handler, not a fixed list: a new one without the check fails here.
    for (const [, listener] of vi.mocked(ipcMain.handle).mock.calls) {
      vi.mocked(logAuditEvent).mockClear();
      const call = () => (listener as IpcListener)(invokeFrom(url, frame));
      expect(call).toThrow(IpcSenderRefusedError);
      expect(vi.mocked(logAuditEvent).mock.calls).toEqual([
        ["ipc-sender-refused", { reason, origin }],
      ]);
    }
    expect(app.getGPUInfo).not.toHaveBeenCalled();
  });

  it.each(["senderFrame", "url", "mainFrame"] as const)(
    "refuses a sender whose %s throws on read (disposed) by name, logged once",
    (part) => {
      for (const [, listener] of vi.mocked(ipcMain.handle).mock.calls) {
        vi.mocked(logAuditEvent).mockClear();
        const call = () => (listener as IpcListener)(invokeDisposed(part));
        expect(call).toThrow(IpcSenderRefusedError);
        expect(vi.mocked(logAuditEvent).mock.calls).toEqual([
          ["ipc-sender-refused", { reason: "frame-unavailable", origin: "invalid-url" }],
        ]);
      }
    },
  );

  it("the renderer sees the error's name and a fixed message, nothing about the sender", () => {
    const shown = String(new IpcSenderRefusedError());
    expect(shown).toBe("IpcSenderRefusedError: IPC sender refused: not the shell's own page");
  });
});
