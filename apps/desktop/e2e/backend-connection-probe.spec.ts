import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import http from "node:http";
import path from "node:path";
import type { Duplex } from "node:stream";
import { fileURLToPath, pathToFileURL } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";
import type { ElectronApplication, Page } from "@playwright/test";
import type { HardeningFlags } from "../src/main/shellPort.js";

// #3519 S2: what the repo's Electron does when the app:// page talks to a loopback backend, for the
// browser-engine assumptions A1 to A11 of ADR-0038. Each measurement is logged as one
// `CV-PROBE {json}` line, then pinned as S2 measured it (ADR-0038 Amendment 1): a change, for
// example from an Electron bump, fails with the assumption's id and the record's consequence.
// Loopback only, no other network (C-13.7).
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
const STRICT_LAX = ["cvprobe-lax", "cvprobe-strict"];
const PLANTED = ["cvprobe-lax-jar", "cvprobe-strict-jar"];
const NONE_SECURE = ["__Host-cvprobe-host", "cvprobe-none"];
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
  a10: ["cvprobe-a10=1; Path=/; Secure; SameSite=None"],
};

/** ADR-0038's "if it does not hold" consequence per pinned assumption (3b: the token header). */
const IF_NOT = {
  A1: "the record is void (SR-042 never lists null); re-open it",
  A2: "re-check 4b; it may become unnecessary",
  A3: "owner decision D3 (TLS on loopback)",
  A4: "leave Partitioned out (4c)",
  A5: "no design change (the header path still works); update the S2 amendment",
  A6: "windows fall back to the recovery path (3d)",
  A7: "D3; until then a leftover cookie names a revoked session (4b)",
  A8: "owner decision D3 (TLS on loopback); a local-network console line means A9 instead",
  A9: "a preflight: S3 answers it (allow_private_network); a permission: owner decision D7",
  A10: "on the desktop, S6b sends the telemetry POST without keepalive",
  "3b": "the page cannot read the X-CSRF-Token response header; re-open 3b and 3c",
} as const;

/**
 * Logs and soft-asserts S2's measurements for one assumption (what -> [actual, expected]), so every
 * changed assumption shows up in the same run with ADR-0038's consequence.
 */
function pin(
  id: keyof typeof IF_NOT,
  checks: Readonly<Record<string, readonly [actual: unknown, expected: unknown]>>,
): void {
  for (const [what, [actual, expected]] of Object.entries(checks)) {
    probe(id, what, actual);
    const message = `ADR-0038 ${id} no longer holds: ${what}. Consequence: ${IF_NOT[id]}`;
    expect.soft(actual, message).toEqual(expected);
  }
}

/** Logs and soft-asserts one precondition of the pinned measurements. */
function harness(what: string, actual: unknown, expected: unknown): void {
  probe("harness", what, actual);
  expect.soft(actual, `harness: ${what}`).toEqual(expected);
}

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

/** The listed cookie names present in a list, sorted, so a pin never depends on other probes. */
function own(list: readonly string[] | null, names: readonly string[]): string[] | null {
  return pick(list, names)?.sort() ?? null;
}

/** The listed cookies in the jar as "name sameSite secure|not-secure", sorted. */
function stored(
  jar: readonly { name: string; sameSite: string; secure: boolean }[] | null,
  names: readonly string[],
): string[] | null {
  const shown = pick(jar, names)?.map(
    (e) => `${e.name} ${e.sameSite} ${e.secure ? "secure" : "not-secure"}`,
  );
  return shown?.sort() ?? null;
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

/** Binds 127.0.0.1:8000. The meta CSP admits no other port, so a taken port fails the harness. */
function listen(server: http.Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.once("error", (error: NodeJS.ErrnoException) => {
      const taken = "harness: 127.0.0.1:8000 is taken; the meta CSP admits no other port";
      reject(error.code === "EADDRINUSE" ? new Error(taken) : error);
    });
    server.listen(PREFERRED_PORT, "127.0.0.1", () => resolve());
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
  await listen(server);
  const forProbe = (id: string) => seen.filter((entry) => entry.probe === id);
  return {
    port: PREFERRED_PORT,
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
  // XDG_CONFIG_HOME (Linux) and the --user-data-dir launch argument give the run its own profile:
  // an empty cookie jar at the start, and nothing left in a developer's profile afterwards.
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
      // A6's probe window: HARDENED_WEB_PREFERENCES plus webviewTag:false and show:false, created
      // from the main process only inside this test and destroyed in its finally.
      // nosemgrep: cv-electron-unsafe-webprefs reason=A6-probe-second-window-hardened-prefs-main-process-test-only-destroyed-in-finally owner=@CandleViewer/security review=2027-04-16
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

test.describe("Backend connection probe (#3519 S2): ADR-0038 A1 to A11 as measured", () => {
  test("the app:// page reaches a loopback backend as S2 measured it", async () => {
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
    /** Origins other than the app's on the requests of one probe that reached the fixture. */
    const foreign = (id: string) =>
      fixture.forProbe(id).flatMap((entry) => (entry.origin === APP_ORIGIN ? [] : [entry.origin]));
    const response200 = expect.objectContaining({ outcome: "response", status: 200 });
    try {
      expect(fixture.port, "harness: the fixture listens on 127.0.0.1:8000").toBe(PREFERRED_PORT);
      probe("harness", "fixture", { port: fixture.port });

      const profile = `--user-data-dir=${path.join(configHome, "user-data")}`;
      const env = launchEnv(base, configHome);
      const shell = await electron.launch({ args: [MAIN_ENTRY, profile], env });
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

      // A1, A8, A9, 3b: cookie-free requests from the page. A1 checks the Origin of what arrived;
      // whether it arrived is A8's or A9's, so a blocked request never reads as a wrong Origin.
      const get = await run("a1-get", "/echo");
      probe("A1", "fetch-get", get);
      const post = await run("a1-post", "/echo", CSRF_POST);
      probe("A1", "fetch-preflighted-post", post);
      const pna = await run("a9-pna", "/echo?pna=1", CSRF_POST);
      probe("A9", "preflight-allows-private-network", pna);
      const socket = await measure(() => pageSocket(win, `${wsBase}/ws?probe=a1-ws`));
      probe("A1", "websocket", { page: socket, server: fixture.forProbe("a1-ws") });
      pin("A8", {
        "the fetch of http://127.0.0.1 gets its response": [get.page, response200],
        "the preflighted POST gets its response": [post.page, response200],
        "the ws://127.0.0.1 upgrade opens": [socket, { outcome: "open" }],
      });
      const origins = ["a1-get", "a1-post", "a1-ws"].flatMap(foreign);
      const postMethods = fixture.forProbe("a1-post").map((entry) => entry.method);
      pin("A1", {
        "Origin is app://candleviewer on GET, preflight, POST, WS": [origins, []],
        "the preflight and the POST both arrive": [postMethods, ["OPTIONS", "POST"]],
      });
      const readable = [get.page, post.page].map((page) =>
        "csrfHeaderReadable" in page ? page.csrfHeaderReadable : "no response (see A8)",
      );
      pin("3b", { "the page reads X-CSRF-Token on the GET and POST": [readable, [true, true]] });
      pin("A9", {
        "a preflight answering Allow-Private-Network works too": [pna.page, response200],
      });

      // A2, A3, A4: one cross-site response sets a cookie per form; then the jar and what is sent.
      const set = await run("a2-set", "/set?cookies=samesite");
      const jar = await readJar(shell);
      // A2's other half: Strict and Lax cookies put in the jar directly; does the page send them?
      const plant = await measure(() =>
        shell.evaluate(async ({ session }, url) => {
          const { cookies } = session.defaultSession;
          await cookies.set({ url, name: "cvprobe-strict-jar", value: "1", sameSite: "strict" });
          await cookies.set({ url, name: "cvprobe-lax-jar", value: "1", sameSite: "lax" });
          return "planted";
        }, `${base}/`),
      );
      const echo = await run("a2-echo", "/echo");
      const ownPost = await run("a3-post", "/echo", CSRF_POST);
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
      const ran = [set.page, echo.page, ownPost.page, plant, mainFetch, jar === null];
      const ranOk = [response200, response200, response200, "planted", 200, false];
      harness("the cookie probes ran", ran, ranOk);
      const sentOnGet = fixture.cookiesSent("a2-echo", "GET");
      const strictLax = [...STRICT_LAX, ...PLANTED];
      pin("A2", {
        "Strict/Lax cookies from a cross-site response: not stored": [stored(jar, STRICT_LAX), []],
        "Strict/Lax cookies in the jar: not sent": [own(sentOnGet ?? [], strictLax), []],
      });
      const noneStored = NONE_SECURE.map((name) => `${name} no_restriction secure`);
      const noneSent = [
        own(sentOnGet, NONE_SECURE),
        own(fixture.cookiesSent("a3-post", "POST"), NONE_SECURE),
      ];
      pin("A3", {
        "None/__Host- cookies over http: stored": [stored(jar, NONE_SECURE), noneStored],
        "and sent on the page's GET and POST": [noneSent, [NONE_SECURE, NONE_SECURE]],
      });
      const chips = ["cvprobe-chips"];
      const mainChips = own(fixture.cookiesSent("a4-main", "GET"), [
        "cvprobe-chips",
        "cvprobe-none",
      ]);
      pin("A4", {
        "a Partitioned cookie is stored": [
          stored(jar, chips),
          ["cvprobe-chips no_restriction secure"],
        ],
        "and sent from the page (top-level app://candleviewer)": [own(sentOnGet, chips), chips],
        "a main-process fetch sends only the unpartitioned one": [mainChips, ["cvprobe-none"]],
      });

      // A10: the telemetry transport's request shape, with a cookie of its own.
      await run("a10-set", "/set?cookies=a10");
      const keepalive = await run("a10-keepalive", "/echo", { ...JSON_POST, keepalive: true });
      probe("A10", "keepalive-json-post", keepalive);
      const keptMethods = fixture.forProbe("a10-keepalive").map((entry) => entry.method);
      const keptCookie = own(fixture.cookiesSent("a10-keepalive", "POST"), ["cvprobe-a10"]);
      pin("A10", {
        "the keep-alive JSON POST is preflighted, then sent": [keptMethods, ["OPTIONS", "POST"]],
        "with its cookie": [keptCookie, ["cvprobe-a10"]],
        "and the page gets the response": [keepalive.page, response200],
      });

      // A7: set four cookies, expire them four ways, then the jar and what the page still sends.
      await run("a7-set", "/set?cookies=expiry-targets");
      const jarBefore = await readJar(shell);
      await run("a7-before", "/echo");
      const expiry = await run("a7-expire", "/set?cookies=expire");
      const jarAfter = await readJar(shell);
      await run("a7-echo", "/echo");
      const names = (list: typeof jar) => list?.map((entry) => entry.name) ?? null;
      const sentBefore = fixture.cookiesSent("a7-before", "GET");
      const before = [own(names(jarBefore), EXPIRY_NAMES), own(sentBefore, EXPIRY_NAMES)];
      const after = [
        own(names(jarAfter), EXPIRY_NAMES),
        own(fixture.cookiesSent("a7-echo", "GET"), EXPIRY_NAMES),
      ];
      const all = [...EXPIRY_NAMES].sort();
      harness("the four expiry targets were stored and sent", before, [all, all]);
      harness("the expiry response arrived", expiry.page, response200);
      const kept = ["cvprobe-exp-strict", "cvprobe-exp-unpart"];
      const expiries =
        "an expiry with the same attributes (Partitioned too) removes its cookie; a " +
        "SameSite=Strict expiry or one without Partitioned does not (jar, then sent)";
      pin("A7", { [expiries]: [after, [kept, kept]] });

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
      const visible = Array.isArray(documentCookie)
        ? documentCookie.filter((name) => PROBE_COOKIE.test(name))
        : documentCookie;
      pin("A5", { "document.cookie shows none of the backend's cookies": [visible, []] });

      // A6: BroadcastChannel between two app windows.
      const channel = await measure(() => broadcastBetweenWindows(shell, win));
      const heard = { secondWindowOrigin: APP_ORIGIN, heard: "from-main-window" };
      pin("A6", { "a BroadcastChannel message reaches a second app window": [channel, heard] });

      // A11 and A1's served-worker case need a worker script served by app:// that the page can
      // start. The build ships none yet; when one appears, E17-T04's wiring slice measures them.
      const assets = await fs.readdir(WEB_ASSETS_DIR).catch(() => [] as string[]);
      const workerChunks = assets.filter((file) => /worker/i.test(file));
      const measurable = workerChunks.length > 0;
      const reason = "no worker served by app:// that the page can start; E17-T04 measures it";
      probe("A11", "shared-worker-served-by-app", { measurable, reason, workerChunks });
      probe("A1", "worker-websocket-served-by-app", { measurable, reason });
      if (measurable) {
        const description =
          `A11 and A1's served-worker case became measurable (${workerChunks.join(", ")}); ` +
          "E17-T04's wiring slice measures them";
        test.info().annotations.push({ type: "measurable", description });
      }
      // Supplementary: a blob: SharedWorker has the page's origin but is not served by app://.
      const blob = await measure(() =>
        pageBlobWorker(win, `${wsBase}/ws?probe=a1-blob-ws`, `${base}/echo?probe=a1-blob-fetch`),
      );
      const blobServer = [...fixture.forProbe("a1-blob-ws"), ...fixture.forProbe("a1-blob-fetch")];
      probe("A1", "blob-shared-worker", { page: blob, server: blobServer });
      const blobResult = { outcome: "reported", result: { ws: "open", fetch: 200 } };
      pin("A1", {
        "a blob: SharedWorker (supplementary) opens its socket and fetches": [blob, blobResult],
        "with Origin app://candleviewer": [
          [...foreign("a1-blob-ws"), ...foreign("a1-blob-fetch")],
          [],
        ],
      });

      // A8, A9: network preflights, permission requests and the console lines that tell mixed
      // content (A8) from local-network blocking (A9), plus the CSP violations seen on the page.
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
      probe("context", "console", relevant.slice(0, 30));
      probe("context", "csp-violations", violations);
      const unattributed = fixture.seen.filter((entry) => entry.probe === "");
      probe(
        "context",
        "unattributed-requests",
        unattributed.map((e) => `${e.method} ${e.path}`),
      );
      const networkPreflights = fixture.seen
        .filter((entry) => "private-network" in entry.acr || "local-network" in entry.acr)
        .map((entry) => ({ probe: entry.probe, acr: entry.acr }));
      pin("A8", {
        "no mixed-content console line": [relevant.filter((l) => /mixed content/i.test(l)), []],
      });
      pin("A9", {
        "no private-network preflight": [networkPreflights, []],
        "no permission request": [asked, []],
      });
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
