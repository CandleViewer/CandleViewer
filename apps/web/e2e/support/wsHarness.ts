// E08-Q05 (#282) slice 1: a fake 23-ws-protocol.md gateway (`cv.v1.json`) for e2e, in front of the REAL web client. Its
// socket lives in a shared worker, which `page.routeWebSocket` cannot see (it patches frames only), so `SharedWorker` is
// wrapped: the worker's `WebSocket` relays over a BroadcastChannel to a page `WebSocket` that the route answers. Engine,
// codec and close policy run unchanged. `src/` never imports this; the spec checks `dist/` has no `WS_HARNESS_MARKER`.
// No wall clock: server times are a counter over the fixture's epoch, and the test drives every frame.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, WebSocketRoute } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json } from "./api";

/** The BroadcastChannel name, and the string the production-absence check looks for in `dist/`. */
export const WS_HARNESS_MARKER = "cv-e2e-ws-harness";

export type Frame = Readonly<Record<string, unknown>> & { readonly t: string };
export type TickerRow = generated.ws.TickerSymbolTicker["tickers"][number];

/** 13.3 `welcome.heartbeat` (interval >= 1 000, timeout >= 5 000). Defaults are 9.1's 15 s / 45 s. */
export type Heartbeat = { readonly interval_ms: number; readonly timeout_ms: number };

/** What the gateway says past the handshake (15.9, 4.1). */
export interface GatewayOptions {
  /** `system` payloads pushed as `d`s right after a socket's FIRST `auth_ok`, never after a re-auth (15.9 notices). */
  readonly firstAuthSystem?: readonly Readonly<Record<string, unknown>>[];
  /** `auth_ok.token_expires_at_ms` past the server's now (default 600 000); 61 000 makes the client re-auth in place 5 s on (4.1). */
  readonly tokenTtlMs?: number;
  /**
   * Test-only (#304 S10, E04-D02-F11): every data frame's `ts` is this far behind the server's now (default 0), so a
   * consumer's frame age, and the status bar's latency band, can be held (100-249 ms: "slow"). `setFrameAge` moves it.
   */
  readonly ageMs?: number;
}

export interface WsHarness {
  /** Client -> server frames in arrival order, `conn` 1-based; `auth.access_token` is masked to `x`s of its length. */
  readonly frames: readonly { readonly conn: number; readonly frame: Frame }[];
  readonly sent: readonly Frame[]; // server -> client
  /** The closes the client started, with their 4.4 code and reason. */
  readonly clientCloses: readonly { readonly code: number; readonly reason: string }[];
  connections(): number; // sockets opened
  authenticated(): number; // sockets that reached `auth_ok`
  reauthenticated(): number; // in-place re-auths answered (4.1): an `auth` on an authenticated socket
  /** Drops the socket as a lost transport does (1006, RFC 6455 7.1.5) and refuses new ones until `restore()`. */
  kill(): void;
  restore(): void;
  /** The open socket stays open and its server says nothing more, pongs included (9.1), until `resume()`. A new socket is answered. */
  stall(): void;
  resume(): void;
  /** A `system` delta that skips one `s` (3.3, 12.3): the client must `resync` (7.5). */
  desync(): void;
  /** The session revoked (4.3, 9.5): the hub's `bye session_revoked`, then close 4401; no `auth_ok` after it. */
  revokeSession(): void;
  /** The next fixture ticker (BTCUSDT) or `fields`, as a `snap` then `d`s on `ticker.<symbol>` (6.1, 14.8). */
  sendTicker(symbol: string, fields?: Partial<TickerRow>): void;
  /** Test-only: the age of every data frame sent from now on (`GatewayOptions.ageMs`). */
  setFrameAge(ms: number): void;
  /**
   * E17-Q04 (#569): replies to the client's `t` frames wait until `release(t)`. `hello` keeps a new socket in its
   * first connect (E17-D02 row 1); `resync` keeps a stream resyncing (row 9). Each held frame is still logged.
   */
  hold(t: Held): void;
  release(t: Held): void;
  /** E17-Q04: any `system` payload as the next `d` on `system` (15.9: kill_switch, shutdown_notice, connection_quality). */
  sendSystem(body: Readonly<Record<string, unknown>>): void;
  /** E17-Q04: an `err` frame (10.3), which the app shows as a modal, a badge or a toast by its code. */
  sendErr(code: string, message?: string): void;
  /**
   * E17-Q04: the server closes the live socket with `code` and `reason`, its `bye` (4.4) first when given. New sockets
   * are answered (unlike `kill`): whether the client comes back is its close policy's decision (9.2).
   */
  closeWith(
    close: Readonly<{ code: number; reason: string; bye?: Readonly<Record<string, unknown>> }>,
  ): void;
}

/** The client frames whose replies `hold` can keep back. */
export type Held = "hello" | "resync";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
/** The build's version (`apps/web/package.json`, what `__CV_APP_VERSION__` is): no SCR-157 band. */
const BUILD_VERSION = (
  JSON.parse(readFileSync(join(ROOT, "apps/web/package.json"), "utf8")) as { version: string }
).version;
const FIXTURE = "packages/fixtures/bybit/2026-10-05/ws/recorded_tickers_BTCUSDT.jsonl";
/** Bybit v5 `tickers` key:14.8 key, as services/api/candleviewer/api/ticker.py maps them. */
const KEYS = `lastPrice:last_price markPrice:mark_price indexPrice:index_price bid1Price:bid1_price
  bid1Size:bid1_size ask1Price:ask1_price ask1Size:ask1_size price24hPcnt:price_change_pct_24h
  highPrice24h:high_24h lowPrice24h:low_24h volume24h:volume_24h turnover24h:turnover_24h`
  .split(/\s+/)
  .map((pair) => pair.split(":") as [string, string]);

/** The recorded, redacted capture (manifest: capture_fixture.py, 2026-10-19), snapshot merged with each delta. */
export function fixtureTickers(): readonly TickerRow[] {
  const merged: Record<string, string> = {};
  return readFileSync(join(ROOT, FIXTURE), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const { data, ts } = JSON.parse(line) as { data: Record<string, string>; ts: number };
      Object.assign(merged, data);
      const row: Record<string, unknown> = { symbol: merged["symbol"], ts_ms: ts };
      for (const [from, to] of KEYS) if (merged[from]) row[to] = merged[from];
      return row as unknown as TickerRow;
    });
}

const EPOCH_MS = 1_792_391_746_229; // the fixture's first frame: server times count up from it
const HEALTH = { kind: "health", health: "healthy" } as const;
const ID = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

/** Runs in the page (serialised by Playwright): wraps `SharedWorker` and relays the worker's sockets. */
export function pageBridge({ name, shim }: { name: string; shim: string }): void {
  const Real = window.SharedWorker;
  const channel = new BroadcastChannel(name);
  const sockets = new Map<string, WebSocket>();
  window.SharedWorker = function (url: string | URL, opts?: string | WorkerOptions) {
    const entry = JSON.stringify(new URL(String(url), location.href).href);
    // The entry sets `onconnect` once its imports load; a tab that connects sooner is handed over then.
    const src = `${shim}\nconst q=[];self.onconnect=(e)=>q.push(e);import(${entry}).then(()=>{for(const e of q)self.onconnect(e)});`;
    return new Real(URL.createObjectURL(new Blob([src], { type: "text/javascript" })), opts);
  } as unknown as typeof SharedWorker;
  channel.onmessage = ({ data: m }: MessageEvent) => {
    const ws = sockets.get(m.id);
    if (m.k === "open") {
      const s = new WebSocket(m.url, m.protocols);
      sockets.set(m.id, s);
      s.onopen = () => channel.postMessage({ k: "open", id: m.id });
      s.onmessage = (e) => channel.postMessage({ k: "msg", id: m.id, data: e.data });
      s.onclose = (e) => channel.postMessage({ k: "close", id: m.id, code: e.code });
    } else if (m.k === "send") ws?.send(m.data);
    else if (m.k === "close") {
      // A code a page may not send (1002, 4.4) still closes, without the code.
      ws?.close(...(m.code === 1000 || m.code >= 3000 ? [m.code, m.reason] : []));
    }
  };
}

/** Runs in the worker before its entry: a `WebSocket` whose traffic is relayed to the page. */
export function workerShim(name: string): void {
  const channel = new BroadcastChannel(name);
  const sockets = new Map<string, EventTarget>();
  let next = 0;
  class RelaySocket extends EventTarget {
    readonly id = `w${(next += 1)}`;
    constructor(url: string, protocols?: string | string[]) {
      super();
      sockets.set(this.id, this);
      channel.postMessage({ k: "open", id: this.id, url: String(url), protocols });
    }
    send(data: string): void {
      channel.postMessage({ k: "send", id: this.id, data });
    }
    close(code?: number, reason?: string): void {
      channel.postMessage({ k: "close", id: this.id, code, reason });
    }
  }
  channel.onmessage = ({ data: m }: MessageEvent) => {
    const s = sockets.get(m.id);
    if (m.k === "open") s?.dispatchEvent(new Event("open"));
    if (m.k === "msg") s?.dispatchEvent(new MessageEvent("message", { data: m.data }));
    if (m.k === "close") s?.dispatchEvent(new CloseEvent("close", { code: m.code }));
  };
  (self as unknown as { WebSocket: unknown }).WebSocket = RelaySocket;
}

/** `seq`: the last `s` sent per stream (3.3). `authed`: an `auth` was answered, so the next is a re-auth (4.1). */
type Conn = {
  readonly n: number;
  readonly route: WebSocketRoute;
  readonly seq: Map<string, number>;
  authed: boolean;
};

/**
 * Installs the fake gateway on `page`. Call it after `stubSession` and before `goto`: it also answers the refresh with a
 * token the WS client accepts (4.3 / 13.4: 20 characters or more), opaque like the server's.
 */
export async function installWsHarness(
  page: Page,
  heartbeat?: Heartbeat,
  gateway: GatewayOptions = {},
): Promise<WsHarness> {
  return startWsHarness(page, heartbeat, gateway);
}

/** The same fake gateway under the name the E17-Q04 (#569) specs call it by. */
export async function startWsHarness(
  page: Page,
  heartbeat?: Heartbeat,
  gateway: GatewayOptions = {},
): Promise<WsHarness> {
  const frames: { conn: number; frame: Frame }[] = [];
  const sent: Frame[] = [];
  const clientCloses: { code: number; reason: string }[] = [];
  const tickers = fixtureTickers();
  let tick = 0;
  let opened = 0;
  let authed = 0;
  let reauthed = 0;
  let down = false;
  let stalled: Conn | undefined;
  let current: Conn | undefined;
  let ageMs = gateway.ageMs ?? 0;
  const held = new Set<Held>();
  const parked: [Conn, Frame][] = [];
  const now = (): number => EPOCH_MS + (tick += 1);

  const send = (c: Conn, frame: Frame): void => {
    if (c === stalled) return;
    sent.push(frame);
    c.route.send(JSON.stringify(frame));
  };
  const data = (c: Conn, t: "snap" | "d", ch: string, p: unknown, s: number, meta?: object) => {
    c.seq.set(ch, s);
    send(c, { t, ch, s, ts: now() - ageMs, e: "j", ...(meta && { meta }), p });
  };

  /** 4.2, 4.3, 5.2, 5.3, 7.5, 9.1: the replies a gateway owes each client frame. */
  function answer(c: Conn, f: Frame): void {
    if ((f.t === "hello" || f.t === "resync") && held.has(f.t)) return void parked.push([c, f]);
    const p = (f["p"] ?? {}) as Record<string, unknown>;
    const id = f["id"];
    switch (f.t) {
      case "hello":
        return send(c, {
          t: "welcome",
          id,
          ts: now(),
          p: {
            protocol: "cv.v1",
            encoding: "json",
            server_version: BUILD_VERSION,
            connection_id: `ws_e2e_${c.n}`,
            server_time_ms: now(),
            auth_required: true,
            heartbeat: heartbeat ?? { interval_ms: 15_000, timeout_ms: 45_000 },
            limits: {
              max_subscriptions: 200,
              max_topics_per_request: 50,
              max_inbound_frame_bytes: 262_144,
              max_outbound_frame_bytes: 4_194_304,
              min_throttle_ms: 50,
              max_symbols_per_connection: 40,
            },
          },
        });
      case "auth": {
        const first = !c.authed;
        c.authed = true;
        if (first) authed += 1;
        else reauthed += 1;
        const killSwitch = { engaged: false, scope: "global" };
        send(c, {
          t: "auth_ok",
          id,
          ts: now(),
          p: {
            user_id: ID(1),
            roles: ["owner"],
            permissions: ["marketdata:read"],
            account_scope: [],
            allowed_environments: ["demo"],
            session_id: ID(2),
            token_expires_at_ms: now() + (gateway.tokenTtlMs ?? 600_000),
            kill_switch: killSwitch,
          },
        });
        if (!first) return; // 4.1: a re-auth in place is answered by `auth_ok` alone
        // 6.2: `system` is subscribed implicitly at `auth_ok`, and its snapshot follows (12.1).
        data(c, "snap", "system", { ...HEALTH, kill_switch: killSwitch }, 1);
        // 15.9: a first authentication's notices, each a `d` on `system` (the gateway's `push_system`)
        for (const body of gateway.firstAuthSystem ?? [])
          data(c, "d", "system", body, (c.seq.get("system") ?? 0) + 1);
        return;
      }
      case "sub": {
        const topics = ((p["topics"] ?? []) as ({ ch: string } | string)[]).map((t) =>
          typeof t === "string" ? t : t.ch,
        );
        const results = topics.map((ch) => ({ ch, ok: true, sub_id: `s_${now()}`, effective: {} }));
        send(c, { t: "sub_ok", id, ts: now(), p: { results } });
        for (const ch of topics.filter((t) => t.startsWith("ticker.")))
          harness.sendTicker(ch.slice("ticker.".length));
        return;
      }
      case "resync": {
        const ch = String(f["ch"]);
        const last = c.seq.get(ch) ?? 0;
        // Only `system` has a body to re-send here; a ticker resync waits for the next `sendTicker`. Its snapshot is
        // the first one's (12.1), the kill switch included: without it the client keeps the switch unknown (WS-E06).
        const body = { ...HEALTH, kill_switch: { engaged: false, scope: "global" } };
        if (ch === "system")
          data(c, "snap", ch, body, last + 1, { reason: "client_resync", previous_seq: last });
        return;
      }
      case "ping":
        return send(c, { t: "pong", id, ts: now(), p: { server_ms: now() } });
    }
  }

  const tokens = {
    access_token: ["e2e", "ws", "harness", "opaque", "bearer"].join("."),
    token_type: "Bearer",
    expires_in: 600,
    refresh_expires_in: 2_592_000,
  };
  await page.route("**/api/v1/auth/refresh", (r) =>
    r.fulfill(json({ status: "authenticated", tokens })),
  );
  await page.routeWebSocket("**/api/v1/ws", (route) => {
    opened += 1;
    if (down) return route.close({ code: 1006, reason: "harness_kill" });
    const c: Conn = { n: opened, route, seq: new Map(), authed: false };
    current = c;
    route.onMessage((message) => {
      const frame = JSON.parse(String(message)) as Frame;
      const p = frame["p"] as Record<string, unknown> | undefined;
      const mask = "x".repeat(String(p?.["access_token"]).length);
      const kept = frame.t === "auth" ? { ...frame, p: { ...p, access_token: mask } } : frame;
      frames.push({ conn: c.n, frame: kept });
      answer(c, frame);
    });
    route.onClose(
      (code, reason) => void clientCloses.push({ code: code ?? 1005, reason: reason ?? "" }),
    );
  });
  await page.addInitScript(pageBridge, {
    name: WS_HARNESS_MARKER,
    shim: `(${workerShim.toString()})(${JSON.stringify(WS_HARNESS_MARKER)});`,
  });

  const harness: WsHarness = {
    frames,
    sent,
    clientCloses,
    connections: () => opened,
    authenticated: () => authed,
    reauthenticated: () => reauthed,
    kill() {
      down = true;
      void current?.route.close({ code: 1006, reason: "harness_kill" });
      current = undefined;
    },
    restore: () => void (down = false),
    stall: () => void (stalled = current),
    resume: () => void (stalled = undefined),
    desync() {
      if (!current) throw new Error("desync: no live connection");
      const s = (current.seq.get("system") ?? 0) + 2; // s + 1 is never sent
      data(current, "d", "system", HEALTH, s);
    },
    revokeSession() {
      if (!current) throw new Error("revokeSession: no live connection");
      down = true; // a revoked session's next socket is refused (23 4.3: the hub remembers it)
      // services/api/candleviewer/ws/revocation.py `bye_frame` (no `ts`), as `close_for` sends it
      const bye = {
        code: 4401,
        reason: "session_revoked",
        message: "session revoked",
        reconnect: false,
      };
      send(current, { t: "bye", p: bye });
      void current.route.close({ code: 4401, reason: "session_revoked" });
      current = undefined;
    },
    setFrameAge(ms) {
      ageMs = ms;
    },
    hold: (t) => void held.add(t),
    release(t) {
      held.delete(t);
      const due = parked.filter(([, f]) => f.t === t);
      parked.splice(0, parked.length, ...parked.filter(([, f]) => f.t !== t));
      for (const [c, f] of due) answer(c, f);
    },
    sendSystem(body) {
      if (!current) throw new Error("sendSystem: no live connection");
      data(current, "d", "system", body, (current.seq.get("system") ?? 0) + 1);
    },
    sendErr(code, message = code) {
      if (!current) throw new Error("sendErr: no live connection");
      send(current, { t: "err", ts: now(), p: { code, message } });
    },
    closeWith({ code, reason, bye }) {
      if (!current) throw new Error("closeWith: no live connection");
      if (bye !== undefined) send(current, { t: "bye", p: bye });
      void current.route.close({ code, reason });
      current = undefined;
    },
    sendTicker(symbol, fields = {}) {
      if (!current) throw new Error("sendTicker: no live connection");
      const ch = `ticker.${symbol}`;
      const last = current.seq.get(ch);
      const base = symbol === "BTCUSDT" ? tickers[(last ?? 0) % tickers.length] : undefined;
      const row = { ...base, symbol, ...fields } as TickerRow;
      const [t, meta] =
        last === undefined ? (["snap", { reason: "initial" }] as const) : (["d"] as const);
      data(current, t, ch, { tickers: [row] }, (last ?? 0) + 1, meta);
    },
  };
  return harness;
}
