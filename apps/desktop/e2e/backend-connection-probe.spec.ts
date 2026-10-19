import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import type { Duplex } from "node:stream";
import { fileURLToPath, pathToFileURL } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";
import type { ElectronApplication, Page } from "@playwright/test";
import type { HardeningFlags } from "../src/main/shellPort.js";

// #3519 S2, phase 1 (measure): what the repo's Electron does when the app:// page talks to a
// loopback backend, for the browser-engine assumptions A1 to A11 of ADR-0038. Each measurement is
// one `CV-PROBE {json}` line on stdout. The test passes whatever it observes and asserts only that
// its harness worked; phase 2 pins the measured behaviour. Loopback only (C-13.5).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../dist/main/index.js");
const SHELL_PORT_MODULE = path.join(__dirname, "../dist/main/shellPort.js");
const WEB_ASSETS_DIR = path.join(__dirname, "../../web/dist/assets");
const APP_ORIGIN = "app://candleviewer";
// The shell's default backend port. apps/web/index.html's <meta> CSP fallback admits only this
// port and both policies are enforced, so a fixture on any other port is blocked by the meta.
const PREFERRED_PORT = 8000;
const PROBE_MS = 5_000;
// RFC 6455 fixes SHA-1 and this GUID for the handshake's accept value; nothing here is a secret.
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const PROBE_COOKIE = /^(__Host-)?cvprobe-/;
const EXPIRY_NAMES = [
  "cvprobe-exp-same",
  "cvprobe-exp-strict",
  "cvprobe-exp-part",
  "cvprobe-exp-unpart",
];

/** Request presets, built here and passed to the page as plain data. */
interface Init {
  readonly method?: string;
  readonly headers?: Readonly<Record<string, string>>;
  readonly body?: string;
  readonly keepalive?: boolean;
}
const JSON_POST: Init = {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: "{}",
};
const CSRF_POST: Init = {
  ...JSON_POST,
  headers: { "content-type": "application/json", "x-csrf-token": "probe-request-token" },
};

/** Set-Cookie lines per `?cookies=` value. Values are fixed dummies; only names are logged. */
const COOKIE_SETS: Readonly<Record<string, readonly string[]>> = {
  samesite: [
    "cvprobe-strict=1; Path=/; SameSite=Strict",
    "cvprobe-lax=1; Path=/; SameSite=Lax",
    "cvprobe-none=1; Path=/; Secure; SameSite=None",
    "__Host-cvprobe-host=1; Path=/; Secure; SameSite=None",
    "cvprobe-chips=1; Path=/; Secure; SameSite=None; Partitioned",
  ],
  "expiry-targets": [
    "cvprobe-exp-same=1; Path=/; Secure; SameSite=None",
    "cvprobe-exp-strict=1; Path=/; Secure; SameSite=None",
    "cvprobe-exp-part=1; Path=/; Secure; SameSite=None; Partitioned",
    "cvprobe-exp-unpart=1; Path=/; Secure; SameSite=None; Partitioned",
  ],
  // Expiries: the same attributes, SameSite=Strict (today's clear helpers), and a partitioned
  // cookie expired with and without Partitioned.
  expire: [
    "cvprobe-exp-same=; Max-Age=0; Path=/; Secure; SameSite=None",
    "cvprobe-exp-strict=; Max-Age=0; Path=/; Secure; SameSite=Strict",
    "cvprobe-exp-part=; Max-Age=0; Path=/; Secure; SameSite=None; Partitioned",
    "cvprobe-exp-unpart=; Max-Age=0; Path=/; Secure; SameSite=None",
  ],
};

function probe(id: string, testCase: string, observed: unknown): void {
  console.log(`CV-PROBE ${JSON.stringify({ id, case: testCase, observed })}`);
}

function originOf(url: string): string {
  const parsed = new URL(url);
  return `${parsed.protocol}//${parsed.host}`;
}

/** Runs one probe with an outer bound, so a hung page or app cannot stall the others. */
async function measure<T>(work: () => Promise<T>): Promise<T | { probeError: string }> {
  let timer: NodeJS.Timeout | undefined;
  const bound = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error("no answer within the probe bound")), PROBE_MS * 3);
  });
  try {
    return await Promise.race([work(), bound]);
  } catch (error) {
    return { probeError: String(error).slice(0, 300) };
  } finally {
    clearTimeout(timer);
  }
}

/** Keeps the listed names of a cookie list or of jar entries (null stays null: nothing seen). */
function pick<T extends string | { readonly name: string }>(
  list: readonly T[] | null,
  names: readonly string[],
): T[] | null {
  return (
    list?.filter((item) => names.includes(typeof item === "string" ? item : item.name)) ?? null
  );
}

/** One request as the fixture saw it: probe cookie names only, never a cookie value. */
function seenOf(req: http.IncomingMessage, upgrade: boolean) {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const names = (req.headers.cookie ?? "")
    .split(";")
    .map((part) => part.split("=")[0]?.trim() ?? "");
  const prefixed = (prefix: string): Record<string, string> =>
    Object.fromEntries(
      Object.entries(req.headers)
        .filter(([key]) => key.startsWith(prefix))
        .map(([key, value]) => [key.slice(prefix.length), String(value)]),
    );
  return {
    probe: url.searchParams.get("probe") ?? "",
    method: req.method ?? "",
    path: url.pathname,
    upgrade,
    origin: req.headers.origin ?? null,
    cookies: names.filter((name) => PROBE_COOKIE.test(name)),
    otherCookies: names.filter((name) => name !== "" && !PROBE_COOKIE.test(name)).length,
    acr: prefixed("access-control-request-"),
    secFetch: prefixed("sec-fetch-"),
  };
}

/** CORS only for the listed origin, exactly (ADR-0038 2b); `?cookies=` picks the Set-Cookie lines. */
function answer(req: http.IncomingMessage, res: http.ServerResponse): void {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const listed = req.headers.origin === APP_ORIGIN;
  const headers: http.OutgoingHttpHeaders = { vary: "Origin" };
  if (listed) {
    headers["access-control-allow-origin"] = APP_ORIGIN;
    headers["access-control-allow-credentials"] = "true";
  }
  req.resume();
  if (req.method === "OPTIONS") {
    headers["access-control-allow-methods"] = "GET, POST";
    headers["access-control-allow-headers"] = "content-type, x-csrf-token";
    if (url.searchParams.get("pna") === "1") {
      headers["access-control-allow-private-network"] = "true";
    }
    res.writeHead(listed ? 204 : 400, headers).end();
    return;
  }
  headers["access-control-expose-headers"] = "x-csrf-token";
  headers["x-csrf-token"] = "probe-token";
  headers["cache-control"] = "no-store";
  headers["content-type"] = "application/json";
  const cookies = COOKIE_SETS[url.searchParams.get("cookies") ?? ""] ?? [];
  if (cookies.length > 0) {
    headers["set-cookie"] = [...cookies];
  }
  res.writeHead(200, headers).end('{"ok":true}');
}

/** A hand-made WS handshake (no dependency): accept, then end on the first frame the page sends. */
function acceptUpgrade(req: http.IncomingMessage, socket: Duplex, sockets: Set<Duplex>): void {
  sockets.add(socket);
  socket.on("close", () => sockets.delete(socket));
  socket.on("error", () => socket.destroy());
  const key = req.headers["sec-websocket-key"];
  if (typeof key !== "string") {
    socket.destroy();
    return;
  }
  const accept = createHash("sha1").update(`${key}${WS_GUID}`).digest("base64");
  socket.write(
    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  socket.once("data", () => socket.destroy());
}

/** Resolves the bound port, or null when the port is taken. */
function listenOn(server: http.Server, port: number): Promise<number | null> {
  return new Promise((resolve, reject) => {
    const onError = (error: NodeJS.ErrnoException): void => {
      server.off("listening", onListening);
      if (error.code === "EADDRINUSE") {
        resolve(null);
      } else {
        reject(error);
      }
    };
    const onListening = (): void => {
      server.off("error", onError);
      resolve((server.address() as AddressInfo).port);
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, "127.0.0.1");
  });
}

async function startFixture() {
  const seen: ReturnType<typeof seenOf>[] = [];
  const sockets = new Set<Duplex>();
  const server = http.createServer((req, res) => {
    seen.push(seenOf(req, false));
    answer(req, res);
  });
  server.on("upgrade", (req: http.IncomingMessage, socket: Duplex) => {
    seen.push(seenOf(req, true));
    acceptUpgrade(req, socket, sockets);
  });
  const preferred = await listenOn(server, PREFERRED_PORT);
  const port = preferred ?? (await listenOn(server, 0));
  if (port === null) {
    throw new Error("the fixture could not listen on 127.0.0.1");
  }
  const forProbe = (id: string) => seen.filter((entry) => entry.probe === id);
  return {
    port,
    preferredPortBusy: preferred === null,
    seen,
    forProbe,
    /** Probe cookie names sent by the request with this id and method; null if none arrived. */
    cookiesSent: (id: string, method: string): string[] | null =>
      forProbe(id).find((entry) => entry.method === method)?.cookies ?? null,
    close: async (): Promise<void> => {
      for (const socket of sockets) {
        socket.destroy();
      }
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}

/** The runner's environment minus CV_DEV_SERVER_URL (the app:// load path), plus the backend. */
function launchEnv(backendOrigin: string, configHome: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && key !== "CV_DEV_SERVER_URL") {
      env[key] = value;
    }
  }
  // On Linux XDG_CONFIG_HOME gives the run its own profile: an empty cookie jar at the start, and
  // nothing left in a developer's profile afterwards.
  return { ...env, CV_BACKEND_ORIGIN: backendOrigin, XDG_CONFIG_HOME: configHome };
}

/** A credentialed CORS fetch from the page; resolves its outcome and never rejects. */
function pageFetch(win: Page, url: string, init: Init) {
  return win.evaluate(
    async ({ url, init, ms }) => {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), ms);
      try {
        const response = await fetch(url, {
          ...init,
          credentials: "include",
          mode: "cors",
          signal: abort.signal,
        });
        const csrfHeaderReadable = response.headers.get("x-csrf-token") === "probe-token";
        return { outcome: "response", status: response.status, csrfHeaderReadable };
      } catch (error) {
        return { outcome: "rejected", error: String(error) };
      } finally {
        clearTimeout(timer);
      }
    },
    { url, init, ms: PROBE_MS },
  );
}

/** Opens a WebSocket from the page: open, close (with its code), a throw or a timeout. */
function pageSocket(win: Page, url: string): Promise<unknown> {
  return win.evaluate(
    ({ url, ms }) =>
      new Promise((resolve) => {
        interface Socket {
          onopen: (() => void) | null;
          onclose: ((event: { code: number }) => void) | null;
          close(): void;
        }
        const page = globalThis as unknown as { WebSocket: new (url: string) => Socket };
        let socket: Socket;
        try {
          socket = new page.WebSocket(url);
        } catch (error) {
          resolve({ outcome: "threw", error: String(error) });
          return;
        }
        const timer = setTimeout(() => resolve({ outcome: "timeout" }), ms);
        socket.onopen = () => {
          clearTimeout(timer);
          resolve({ outcome: "open" });
          socket.close();
        };
        socket.onclose = (event) => {
          clearTimeout(timer);
          resolve({ outcome: "closed", code: event.code });
        };
      }),
    { url, ms: PROBE_MS },
  );
}

/**
 * A SharedWorker from a blob: URL (the page's origin, but not a script served by app://) that
 * opens a WebSocket and makes one credentialed fetch, then reports both outcomes.
 */
function pageBlobWorker(win: Page, wsUrl: string, httpUrl: string): Promise<unknown> {
  return win.evaluate(
    ({ wsUrl, httpUrl, ms }) =>
      new Promise((resolve) => {
        const source = `onconnect = (event) => {
          const port = event.ports[0], result = {};
          const report = (key, value) => {
            if (!(key in result)) result[key] = value;
            if ("ws" in result && "fetch" in result) port.postMessage(result);
          };
          try {
            const socket = new WebSocket(${JSON.stringify(wsUrl)});
            socket.onopen = () => { report("ws", "open"); socket.close(); };
            socket.onclose = (closed) => report("ws", "closed " + closed.code);
          } catch (error) { report("ws", "threw " + error); }
          fetch(${JSON.stringify(httpUrl)}, { credentials: "include" })
            .then((response) => report("fetch", response.status))
            .catch((error) => report("fetch", "rejected " + error));
        };`;
        interface Shared {
          onerror: (() => void) | null;
          readonly port: { onmessage: ((event: { data: unknown }) => void) | null };
        }
        const page = globalThis as unknown as { SharedWorker: new (url: string) => Shared };
        const timer = setTimeout(() => resolve({ outcome: "timeout" }), ms);
        const settle = (result: unknown): void => {
          clearTimeout(timer);
          resolve(result);
        };
        try {
          const blob = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
          const worker = new page.SharedWorker(blob);
          worker.onerror = () => settle({ outcome: "error-event" });
          worker.port.onmessage = (event) => settle({ outcome: "reported", result: event.data });
        } catch (error) {
          settle({ outcome: "threw", error: String(error) });
        }
      }),
    { wsUrl, httpUrl, ms: PROBE_MS },
  );
}

/** The probe cookies in the shell's cookie jar (main process): names and attributes, no values. */
async function readJar(app: ElectronApplication) {
  try {
    return await app.evaluate(async ({ session }) =>
      (await session.defaultSession.cookies.get({}))
        .filter((cookie) => /^(__Host-)?cvprobe-/.test(cookie.name))
        .map(({ name, sameSite, secure }) => ({ name, sameSite, secure: secure === true })),
    );
  } catch {
    return null;
  }
}

/**
 * A6: a second window on app://candleviewer/, created from the main process with the shell's
 * hardened webPreferences (no product change; the shell denies window.open), and one
 * BroadcastChannel message from the main window to it.
 */
async function broadcastBetweenWindows(app: ElectronApplication, win: Page): Promise<unknown> {
  const { HARDENED_WEB_PREFERENCES } = (await import(pathToFileURL(SHELL_PORT_MODULE).href)) as {
    HARDENED_WEB_PREFERENCES: HardeningFlags;
  };
  const opened = app.waitForEvent("window", { timeout: PROBE_MS * 2 });
  opened.catch(() => undefined); // awaited below; this only keeps an early exit from leaving it unhandled
  const windowId = await app.evaluate(
    ({ BrowserWindow }, { prefs, url }) => {
      const second = new BrowserWindow({
        show: false,
        webPreferences: { ...prefs, webviewTag: false },
      });
      void second.loadURL(url);
      return second.id;
    },
    { prefs: HARDENED_WEB_PREFERENCES, url: `${APP_ORIGIN}/` },
  );
  interface ChannelPage {
    BroadcastChannel: new (name: string) => {
      onmessage: ((event: { data: unknown }) => void) | null;
      postMessage(data: unknown): void;
      close(): void;
    };
    cvProbeHeard: unknown;
  }
  try {
    const second = await opened;
    await second.waitForLoadState("domcontentloaded");
    await second.evaluate((ms) => {
      const page = globalThis as unknown as ChannelPage;
      const channel = new page.BroadcastChannel("cvprobe-a6");
      page.cvProbeHeard = new Promise((resolve) => {
        const timer = setTimeout(() => resolve(null), ms);
        channel.onmessage = (event) => {
          clearTimeout(timer);
          resolve(event.data);
        };
      });
    }, PROBE_MS);
    await win.evaluate(() => {
      const channel = new (globalThis as unknown as ChannelPage).BroadcastChannel("cvprobe-a6");
      channel.postMessage("from-main-window");
      channel.close();
    });
    const heard = await second.evaluate(() => (globalThis as unknown as ChannelPage).cvProbeHeard);
    return { secondWindowOrigin: originOf(second.url()), heard };
  } finally {
    await app.evaluate(({ BrowserWindow }, id) => BrowserWindow.fromId(id)?.destroy(), windowId);
  }
}

test.describe("Backend connection probe, measure mode (#3519 S2, ADR-0038 A1 to A11)", () => {
  test("logs what the app:// page does against a loopback backend", async () => {
    test.setTimeout(150_000);
    const configHome = test.info().outputPath("xdg-config");
    await fs.mkdir(configHome, { recursive: true });
    const fixture = await startFixture();
    const base = `http://127.0.0.1:${fixture.port}`;
    const wsBase = `ws://127.0.0.1:${fixture.port}`;
    let app: ElectronApplication | undefined;
    let isolated = false;
    const quietly = async (step: string, work: () => Promise<unknown>): Promise<void> => {
      try {
        await work();
      } catch (error) {
        probe("harness", "cleanup-error", { step, error: String(error).slice(0, 200) });
      }
    };
    try {
      expect(fixture.port).toBeGreaterThan(0);
      const { port, preferredPortBusy } = fixture;
      probe("harness", "fixture", {
        port,
        preferredPortBusy,
        metaCspAdmits: port === PREFERRED_PORT,
      });

      const shell = await electron.launch({ args: [MAIN_ENTRY], env: launchEnv(base, configHome) });
      app = shell;
      const win = await shell.firstWindow();
      const consoleLines: string[] = [];
      win.on("console", (message) => {
        if (consoleLines.length < 300) {
          consoleLines.push(`${message.type()}: ${message.text()}`.slice(0, 300));
        }
      });
      // The harness check: the web app renders over app:// (no backend session: the sign-in screen).
      await expect(win.locator("#root main")).toBeVisible();
      expect(originOf(win.url())).toBe(APP_ORIGIN);
      const runtime = await shell.evaluate(
        ({ app: electronApp }, home) => ({
          electron: process.versions["electron"] ?? "",
          chrome: process.versions["chrome"] ?? "",
          userDataIsolated: electronApp.getPath("userData").startsWith(home),
        }),
        configHome,
      );
      isolated = runtime.userDataIsolated;
      probe("harness", "app", runtime);

      // A9: the shell's own decision (installPermissionHandler in main/index.ts denies every
      // request) in a copy that also records what was asked. No permission-check handler is set.
      await shell.evaluate(({ session }) => {
        const asked: { permission: string; requesting: string }[] = [];
        Object.assign(globalThis, { cvProbeAsked: asked });
        session.defaultSession.setPermissionRequestHandler(
          (_contents, permission, done, details) => {
            asked.push({ permission, requesting: details.requestingUrl.slice(0, 40) });
            done(false);
          },
        );
      });
      await win.evaluate(() => {
        interface Violation {
          readonly blockedURI: string;
          readonly effectiveDirective: string;
        }
        const violations: string[] = [];
        const page = globalThis as unknown as {
          document: { addEventListener(type: string, listener: (event: Violation) => void): void };
        };
        Object.assign(globalThis, { cvProbeViolations: violations });
        page.document.addEventListener("securitypolicyviolation", (event) => {
          violations.push(`${event.effectiveDirective} ${event.blockedURI}`);
        });
      });

      /** One fetch probe from the page: its outcome and every request of it the fixture saw. */
      const run = async (id: string, route: string, init: Init = {}) => {
        const url = `${base}${route}${route.includes("?") ? "&" : "?"}probe=${id}`;
        const page = await measure(() => pageFetch(win, url, init));
        return { page, server: fixture.forProbe(id) };
      };

      // A1, A8, A9: a simple credentialed GET, before any cookie exists.
      probe("A1", "fetch-get", await run("a1-get", "/echo"));
      // A2, A3, A4: one response sets a cookie per form; then the jar and what the page sends.
      const set = await run("a2-set", "/set?cookies=samesite");
      const jar = await readJar(shell);
      // A2's other half: Strict and Lax cookies put in the jar directly; does the page send them?
      const planted = ["cvprobe-strict-planted", "cvprobe-lax-planted"];
      const plant = await measure(() =>
        shell.evaluate(async ({ session }, url) => {
          await session.defaultSession.cookies.set({
            url,
            name: "cvprobe-strict-planted",
            value: "1",
            sameSite: "strict",
          });
          await session.defaultSession.cookies.set({
            url,
            name: "cvprobe-lax-planted",
            value: "1",
            sameSite: "lax",
          });
          return "planted";
        }, `${base}/`),
      );
      const echo = await run("a2-echo", "/echo");
      const sentOnGet = fixture.cookiesSent("a2-echo", "GET");
      const strictLax = ["cvprobe-strict", "cvprobe-lax"];
      probe("A2", "samesite-strict-lax", {
        pages: { set: set.page, echo: echo.page },
        stored: pick(jar, strictLax),
        sent: pick(sentOnGet, strictLax),
        plant,
        sentPlanted: pick(sentOnGet, planted),
      });
      // A4: sent from the page (top-level site app://candleviewer) and from the main process.
      const mainFetch = await measure(() =>
        shell.evaluate(async ({ session }, url) => {
          try {
            return (await session.defaultSession.fetch(url, { credentials: "include" })).status;
          } catch (error) {
            return String(error);
          }
        }, `${base}/echo?probe=a4-main`),
      );
      probe("A4", "partitioned", {
        stored: pick(jar, ["cvprobe-chips"]),
        sentFromPage: pick(sentOnGet, ["cvprobe-chips"]),
        mainProcess: { fetch: mainFetch, sent: fixture.cookiesSent("a4-main", "GET") },
      });
      probe("A1", "fetch-preflighted-post", await run("a1-post", "/echo", CSRF_POST));
      const noneSecure = ["cvprobe-none", "__Host-cvprobe-host"];
      probe("A3", "samesite-none-secure", {
        stored: pick(jar, noneSecure),
        sentOnGet: pick(sentOnGet, noneSecure),
        sentOnPost: pick(fixture.cookiesSent("a1-post", "POST"), noneSecure),
      });
      probe(
        "A9",
        "preflight-allows-private-network",
        await run("a9-pna", "/echo?pna=1", CSRF_POST),
      );
      // A10: the telemetry transport's request shape (lib/telemetry/aggregator.ts fetchTransport).
      const keepalive: Init = { ...JSON_POST, keepalive: true };
      probe("A10", "keepalive-json-post", await run("a10-keepalive", "/echo", keepalive));
      // A1, A8: the WS upgrade from the page.
      const socket = await measure(() => pageSocket(win, `${wsBase}/ws?probe=a1-ws`));
      probe("A1", "websocket", { page: socket, server: fixture.forProbe("a1-ws") });

      // A7: set four cookies, expire them four ways, then the jar and what the page still sends.
      const expirySet = await run("a7-set", "/set?cookies=expiry-targets");
      const jarBefore = await readJar(shell);
      await run("a7-before", "/echo");
      const expiry = await run("a7-expire", "/set?cookies=expire");
      const jarAfter = await readJar(shell);
      await run("a7-echo", "/echo");
      probe("A7", "expiry", {
        pages: { set: expirySet.page, expire: expiry.page },
        storedBefore: pick(jarBefore, EXPIRY_NAMES)?.map((entry) => entry.name) ?? null,
        storedAfter: pick(jarAfter, EXPIRY_NAMES)?.map((entry) => entry.name) ?? null,
        sentBefore: pick(fixture.cookiesSent("a7-before", "GET"), EXPIRY_NAMES),
        sentAfter: pick(fixture.cookiesSent("a7-echo", "GET"), EXPIRY_NAMES),
      });

      // A5: the page's document.cookie (names only).
      const documentCookie = await measure(() =>
        win.evaluate(() => {
          try {
            const page = globalThis as unknown as { document: { cookie: string } };
            return page.document.cookie.split(";").map((part) => part.split("=")[0]?.trim() ?? "");
          } catch (error) {
            return String(error);
          }
        }),
      );
      probe("A5", "document-cookie", documentCookie);
      // A6: BroadcastChannel between two app windows.
      probe("A6", "broadcast-channel", await measure(() => broadcastBetweenWindows(shell, win)));

      // A11 and A1's worker part need a worker script served by app:// that the page can start.
      const assets = await fs.readdir(WEB_ASSETS_DIR).catch(() => [] as string[]);
      const reason =
        "the built web app ships no worker the page can start (lib/ws is not reachable from " +
        "main.tsx yet), and S2 adds no shipped asset";
      const workerChunks = assets.filter((file) => /worker/i.test(file));
      probe("A11", "shared-worker-served-by-app", { measurable: false, reason, workerChunks });
      probe("A1", "worker-websocket-served-by-app", { measurable: false, reason });
      // Supplementary: a blob: SharedWorker has the page's origin but is not served by app://.
      const blob = await measure(() =>
        pageBlobWorker(win, `${wsBase}/ws?probe=a1-blob-ws`, `${base}/echo?probe=a1-blob-fetch`),
      );
      const blobServer = [...fixture.forProbe("a1-blob-ws"), ...fixture.forProbe("a1-blob-fetch")];
      probe("A1", "blob-shared-worker", { page: blob, server: blobServer });

      // A8, A9: what reached the server, network preflights, permission requests, and the console
      // lines on loopback, mixed content or local-network blocking. Together with the CSP
      // violations they tell a blocked request apart from a missing or wrong Origin (A1).
      const asked = await measure(() =>
        shell.evaluate(
          () => (globalThis as unknown as { cvProbeAsked?: unknown }).cvProbeAsked ?? null,
        ),
      );
      const violations = await measure(() =>
        win.evaluate(
          () =>
            (globalThis as unknown as { cvProbeViolations?: unknown }).cvProbeViolations ?? null,
        ),
      );
      const relevant = consoleLines.filter(
        (line) =>
          line.includes(`127.0.0.1:${fixture.port}`) ||
          /mixed content|private network|local network|address space|loopback/i.test(line),
      );
      probe("A8", "loopback-from-secure-page", {
        fetchReached: fixture.cookiesSent("a1-get", "GET") !== null,
        websocketReached: fixture.forProbe("a1-ws").some((entry) => entry.upgrade),
        messages: relevant.filter((line) => /mixed content|insecure/i.test(line)).slice(0, 10),
      });
      probe("A9", "local-network", {
        networkPreflights: fixture.seen
          .filter((entry) => "private-network" in entry.acr || "local-network" in entry.acr)
          .map((entry) => ({ probe: entry.probe, acr: entry.acr })),
        permissionRequests: asked,
        messages: relevant
          .filter((line) => /private network|local network|address space|permission/i.test(line))
          .slice(0, 10),
      });
      probe("context", "console", relevant.slice(0, 30));
      probe("context", "csp-violations", violations);
      const unattributed = fixture.seen.filter((entry) => entry.probe === "");
      probe(
        "context",
        "unattributed-requests",
        unattributed.map((e) => `${e.method} ${e.path}`),
      );
    } finally {
      const shell = app;
      if (shell !== undefined && !isolated) {
        await quietly("drop-cookies", () =>
          shell.evaluate(async ({ session }, url) => {
            for (const cookie of await session.defaultSession.cookies.get({})) {
              if (/^(__Host-)?cvprobe-/.test(cookie.name)) {
                await session.defaultSession.cookies.remove(url, cookie.name);
              }
            }
          }, `${base}/`),
        );
      }
      await quietly("close-app", async () => shell?.close());
      await quietly("close-fixture", () => fixture.close());
      await quietly("remove-profile", () => fs.rm(configHome, { recursive: true, force: true }));
    }
  });
});
