// E10-Q04 loopback stub backend (BQ-Q04-08, C-13.5): one 127.0.0.1 origin, ephemeral port, that
// serves the built apps/web, answers the shell's boot REST calls from a path → body table, and
// speaks just enough of the `cv.v1.json` gateway (23 §4) for the first live link: `welcome`,
// `auth_ok` plus the implicit `system` snapshot, `sub_ok`, `pong`. No network past loopback, no
// dependency: the WebSocket framing (RFC 6455, text frames only) is the few lines below.
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import type { Duplex } from "node:stream";

// RFC 6455 fixes this GUID for the handshake's accept value; nothing here is a secret.
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const TYPES: Readonly<Record<string, string>> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

/** One server → client frame (unmasked, FIN); the gateway's frames stay under 64 KiB. */
export function encodeFrame(text: string, opcode = 0x1): Buffer {
  const body = Buffer.from(text, "utf8");
  const n = body.length;
  const head = n < 126 ? [0x80 | opcode, n] : [0x80 | opcode, 126, n >> 8, n & 0xff];
  return Buffer.concat([Buffer.from(head), body]);
}

export interface WsFrame {
  readonly opcode: number;
  readonly payload: Buffer;
}

/** Complete frames at the head of `buf` (masked or not, ≤ 64 KiB), and any partial one's bytes. */
export function decodeFrames(buf: Buffer): { frames: WsFrame[]; rest: Buffer } {
  const frames: WsFrame[] = [];
  let at = 0;
  for (;;) {
    if (buf.length - at < 2) break;
    const b1 = buf[at + 1] as number;
    let len = b1 & 0x7f;
    let off = at + 2;
    if (len === 126) {
      if (buf.length < off + 2) break;
      len = buf.readUInt16BE(off);
      off += 2;
    } else if (len === 127) {
      // The 8-byte length form (frames over 64 KiB): the gateway never sends one, so refuse
      // it rather than misread the payload.
      throw new RangeError("stub backend: WebSocket frames over 64 KiB are not supported");
    }
    const masked = (b1 & 0x80) !== 0;
    const mask = masked ? buf.subarray(off, off + 4) : undefined;
    if (masked) off += 4;
    if (buf.length < off + len) break;
    const payload = Buffer.from(buf.subarray(off, off + len));
    if (mask)
      for (let i = 0; i < len; i += 1)
        payload[i] = (payload[i] as number) ^ (mask[i % 4] as number);
    frames.push({ opcode: (buf[at] as number) & 0x0f, payload });
    at = off + len;
  }
  return { frames, rest: buf.subarray(at) };
}

type Frame = Readonly<Record<string, unknown>> & { readonly t: string };
const ID = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

/** The replies the gateway owes one client frame (as apps/web's e2e wsHarness answers them). */
export function gatewayReplies(f: Frame, version: string, now: () => number): Frame[] {
  const p = (f["p"] ?? {}) as Record<string, unknown>;
  const id = f["id"];
  switch (f.t) {
    case "hello":
      return [
        {
          t: "welcome",
          id,
          ts: now(),
          p: {
            protocol: "cv.v1",
            encoding: "json",
            server_version: version,
            connection_id: "ws_perf_1",
            server_time_ms: now(),
            auth_required: true,
            heartbeat: { interval_ms: 15_000, timeout_ms: 45_000 },
            limits: {
              max_subscriptions: 200,
              max_topics_per_request: 50,
              max_inbound_frame_bytes: 262_144,
              max_outbound_frame_bytes: 4_194_304,
              min_throttle_ms: 50,
              max_symbols_per_connection: 40,
            },
          },
        },
      ];
    case "auth": {
      const killSwitch = { engaged: false, scope: "global" };
      return [
        {
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
            token_expires_at_ms: now() + 600_000,
            kill_switch: killSwitch,
          },
        },
        // 6.2: `system` is subscribed implicitly at `auth_ok`; its snapshot follows (12.1).
        {
          t: "snap",
          ch: "system",
          s: 1,
          ts: now(),
          e: "j",
          p: { kind: "health", health: "healthy", kill_switch: killSwitch },
        },
      ];
    }
    case "sub": {
      const topics = ((p["topics"] ?? []) as ({ ch: string } | string)[]).map((t) =>
        typeof t === "string" ? t : t.ch,
      );
      const results = topics.map((ch) => ({ ch, ok: true, sub_id: `s_${ch}`, effective: {} }));
      return [{ t: "sub_ok", id, ts: now(), p: { results } }];
    }
    case "ping":
      return [{ t: "pong", id, ts: now(), p: { server_ms: now() } }];
    default:
      return [];
  }
}

export interface StubOptions {
  /** The built web app (`apps/web/dist`). */
  readonly webRoot: string;
  /** REST answers by exact pathname, any method. */
  readonly rest: Readonly<Record<string, unknown>>;
  /** `welcome.server_version`: the web build's version, so no version-skew band shows. */
  readonly version: string;
  readonly now?: () => number;
}

export interface StubBackend {
  readonly origin: string;
  /** `METHOD /path` of every `/api` request the table did not answer. */
  unanswered(): string[];
  close(): Promise<void>;
}

export async function startStubBackend(opts: StubOptions): Promise<StubBackend> {
  const now = opts.now ?? Date.now;
  const misses = new Set<string>();
  const root = path.resolve(opts.webRoot);
  const sockets = new Set<Duplex>();

  const server = http.createServer((req, res) => {
    const { pathname } = new URL(req.url ?? "/", "http://127.0.0.1");
    if (Object.hasOwn(opts.rest, pathname)) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(opts.rest[pathname]));
      return;
    }
    if (pathname.startsWith("/api/")) {
      misses.add(`${req.method ?? "GET"} ${pathname}`);
      res.writeHead(404).end();
      return;
    }
    // Static, inside the web root only; an extensionless path is the SPA's index.html.
    const file = path.resolve(root, `.${path.extname(pathname) === "" ? "/index.html" : pathname}`);
    if (!file.startsWith(root + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    readFile(file).then(
      (body) =>
        res
          .writeHead(200, {
            "content-type": TYPES[path.extname(file)] ?? "application/octet-stream",
          })
          .end(body),
      () => res.writeHead(404).end(),
    );
  });

  server.on("upgrade", (req, socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    const key = req.headers["sec-websocket-key"];
    if (
      new URL(req.url ?? "/", "http://127.0.0.1").pathname !== "/api/v1/ws" ||
      typeof key !== "string"
    ) {
      socket.destroy();
      return;
    }
    const accept = createHash("sha1")
      .update(key + WS_GUID)
      .digest("base64");
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
        `Sec-WebSocket-Accept: ${accept}\r\nSec-WebSocket-Protocol: cv.v1.json\r\n\r\n`,
    );
    let pending: Buffer = Buffer.alloc(0);
    socket.on("data", (chunk: Buffer) => {
      let decoded: ReturnType<typeof decodeFrames>;
      try {
        decoded = decodeFrames(Buffer.concat([pending, chunk]));
      } catch {
        socket.destroy();
        return;
      }
      const { frames, rest } = decoded;
      pending = rest;
      for (const f of frames) {
        if (f.opcode === 0x8) socket.end(encodeFrame("", 0x8));
        else if (f.opcode === 0x1) {
          let frame: Frame;
          try {
            frame = JSON.parse(f.payload.toString("utf8")) as Frame;
          } catch {
            socket.destroy(); // a malformed text frame closes the socket, never the stub
            return;
          }
          for (const reply of gatewayReplies(frame, opts.version, now))
            socket.write(encodeFrame(JSON.stringify(reply)));
        }
      }
    });
    socket.on("error", () => socket.destroy());
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    origin: `http://127.0.0.1:${port}`,
    unanswered: () => [...misses].sort(),
    close: async () => {
      for (const s of sockets) s.destroy();
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}
