import { describe, expect, it, vi } from "vitest";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { BrowserWindow, protocol, session } from "electron";
import { buildCsp } from "../src/main/csp";

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

// The default load path is under test: no dev server.
delete process.env["CV_DEV_SERVER_URL"];

const { isNavigationAllowed, safeOriginOf, isExternalLinkAllowed } =
  await import("../src/main/index");

const APP_ROOT = path.resolve(
  process.platform === "win32" ? "C:\\app\\web\\dist" : "/app/web/dist",
);

describe("isNavigationAllowed", () => {
  it("allows the app origin and its client routes when there is no dev server", () => {
    expect(isNavigationAllowed("app://candleviewer/", undefined)).toBe(true);
    expect(isNavigationAllowed("app://candleviewer/login?next=%2Fterminal", undefined)).toBe(true);
  });

  it("denies a file:// URL, even one inside the web app's dist directory", () => {
    const url = pathToFileURL(path.join(APP_ROOT, "index.html")).href;
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
    expect(isNavigationAllowed("http://localhost:5173/", "http://localhost:5173")).toBe(true);
    expect(isNavigationAllowed("http://localhost:5173/route", "http://localhost:5173")).toBe(true);
  });

  it("denies a lookalike host that merely starts with the dev origin string", () => {
    expect(isNavigationAllowed("http://localhost:5173.evil.test/", "http://localhost:5173")).toBe(
      false,
    );
  });

  it("denies a different scheme or port than the dev server", () => {
    expect(isNavigationAllowed("https://localhost:5173/", "http://localhost:5173")).toBe(false);
    expect(isNavigationAllowed("http://localhost:9999/", "http://localhost:5173")).toBe(false);
  });

  it("denies the app origin while a dev server is configured", () => {
    expect(isNavigationAllowed("app://candleviewer/", "http://localhost:5173")).toBe(false);
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

  it("logs only the scheme for a file: URL, never the local path", () => {
    expect(safeOriginOf("file:///home/user/secrets.txt")).toBe("file://");
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

  it("the app:// handler answers with the shell's CSP header and refuses other hosts", async () => {
    await vi.waitFor(() => expect(protocol.handle).toHaveBeenCalled());
    const [scheme, handler] = vi.mocked(protocol.handle).mock.calls[0] ?? [];
    expect(scheme).toBe("app");
    if (handler === undefined) {
      throw new Error("no app:// handler registered");
    }
    const response = await handler(new Request("app://evil.test/index.html"));
    expect(response.status).toBe(404);
    expect(response.headers.get("content-security-policy")).toBe(buildCsp());
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
    expect(appCallback).toHaveBeenCalledWith({});

    const devCallback = vi.fn();
    listener(details("http://127.0.0.1:5173/"), devCallback);
    expect(devCallback).toHaveBeenCalledWith({
      responseHeaders: { "x-a": ["b"], "Content-Security-Policy": [buildCsp()] },
    });
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
