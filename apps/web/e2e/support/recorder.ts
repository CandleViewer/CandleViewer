import type { Page, Route } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json } from "./api";

type Schemas = generated.rest.components["schemas"];
type RecordedSymbol = Schemas["RecordedSymbol"];
type PinBody =
  generated.rest.operations["pinRecordedSymbol"]["requestBody"]["content"]["application/json"];
export type RecorderFrame = generated.ws.Recorder;

export interface RecorderStub {
  /** The recorded set, as the server holds it: the list's items, and what a test pushes as frames. */
  readonly rows: RecordedSymbol[];
  /** The server's row turns `recording`, first recorded at `startedAt`; the next list read carries it. */
  record(symbol: string, startedAt: string): void;
}

/** D02's defaults (decision 1): 60 s dwell, 30 min linger, 20 symbols, 80 / 90 / 95 %. */
export const POLICY = {
  autostart_delay_s: 60,
  autostop_grace_s: 1800,
  max_symbols: 20,
  warn_pct: 80,
  autostop_pct: 90,
  halt_pct: 95,
  autorecord_enabled: true,
} satisfies Schemas["RecorderPolicySettings"];

/** `getStorageUsage`, D02 §3 `running`'s figures: a 200 GB budget, 61.4 GB used, 0.93 GB a day. */
const STORAGE = {
  cap_bytes: 200e9,
  level: 0,
  write_gate: "open",
  write_gate_reason: null,
  accelerate_retention: false,
  daily_growth_bytes: 0.93e9,
  disk_free_bytes: 900e9,
  projected_full_at: null,
  tiers: [
    { tier: "questdb", used_bytes: 41.4e9, retention_days: 7 },
    { tier: "parquet", used_bytes: 20e9, retention_days: 30 },
  ],
  symbols: [],
} satisfies Schemas["StorageUsage"];

/** A `recorder` frame (23 §15.8) for `rows`, each recording unless its state says otherwise. */
export function recorderFrame(rows: readonly RecordedSymbol[]): RecorderFrame {
  return {
    overall: "healthy",
    policy: POLICY,
    connections: [{ state: "connected", subscribed_topics: 4, reconnects_last_hour: 0 }],
    symbols: rows.map((row) => ({
      symbol: row.symbol,
      state: row.state,
      reason: row.reason,
      pinned: row.pinned ?? false,
      disk_bytes: row.disk_bytes ?? 0,
      dropped_messages: 0,
    })),
    storage: {
      used_bytes: 61.4e9,
      cap_bytes: 200e9,
      level: 0,
      write_gate: "open",
      write_gate_reason: null,
      accelerate_retention: false,
      daily_growth_bytes: 0.93e9,
      disk_free_bytes: 900e9,
      projected_full_at_ms: null,
    },
  };
}

/**
 * The recording API at the network layer (no backend, C-13.5), as `22`'s operations answer it: the recorded set in
 * memory, an add (201, `starting`), a pin (200) and a stop (204, the row gone); every other `/recording` read
 * empty.
 */
export async function stubRecorder(page: Page): Promise<RecorderStub> {
  const rows: RecordedSymbol[] = [];
  const list = () => ({
    items: rows,
    meta: { next_cursor: null, has_more: false, count: rows.length },
  });
  await page.route(
    (url) =>
      url.pathname.startsWith("/api/v1/recording") ||
      url.pathname === "/api/v1/market/data-coverage",
    async (route: Route) => {
      const request = route.request();
      const { pathname, searchParams } = new URL(request.url());
      const method = request.method();
      if (pathname === "/api/v1/market/data-coverage") {
        return route.fulfill(json({ symbol: searchParams.get("symbol"), streams: [] }));
      }
      if (pathname === "/api/v1/recording/status") {
        return route.fulfill(json({ overall: "healthy", policy: POLICY, symbols: [] }));
      }
      if (pathname === "/api/v1/recording/storage") return route.fulfill(json(STORAGE));
      if (pathname === "/api/v1/recording/sessions") {
        return route.fulfill(
          json({ items: [], meta: { next_cursor: null, has_more: false, count: 0 } }),
        );
      }
      if (pathname === "/api/v1/recording/symbols" && method === "GET")
        return route.fulfill(json(list()));
      if (pathname === "/api/v1/recording/symbols" && method === "POST") {
        const body = request.postDataJSON() as Schemas["AddRecordedSymbolRequest"];
        const row: RecordedSymbol = {
          id: `e1000000-0000-4000-8000-00000000000${rows.length + 1}`,
          symbol: body.symbol,
          reason: "manual",
          state: "starting",
          pinned: body.pinned ?? false,
          streams: body.streams ?? [],
          depth: body.depth ?? 200,
          retention_days: body.pinned === true ? null : (body.retention_days ?? 30),
          started_at: null,
          disk_bytes: 0,
        };
        rows.push(row);
        return route.fulfill(json(row, 201));
      }
      const pin = /^\/api\/v1\/recording\/symbols\/([^/]+)\/pin$/u.exec(pathname);
      if (pin !== null && method === "PUT") {
        const row = rows.find((r) => r.id === pin[1]);
        if (row === undefined) return route.fulfill(json({ code: "not_found", status: 404 }, 404));
        const body = request.postDataJSON() as PinBody;
        row.pinned = body.pinned;
        row.retention_days = body.pinned ? null : (body.retention_days ?? 30);
        return route.fulfill(json(row));
      }
      const one = /^\/api\/v1\/recording\/symbols\/([^/]+)$/u.exec(pathname);
      if (one !== null && method === "DELETE") {
        const at = rows.findIndex((r) => r.id === one[1]);
        if (at >= 0) rows.splice(at, 1);
        return route.fulfill({ status: 204 });
      }
      return route.fulfill(json({ code: "not_found", status: 404 }, 404));
    },
  );
  return {
    rows,
    record(symbol, startedAt) {
      const at = rows.findIndex((r) => r.symbol === symbol);
      const row = rows[at];
      if (row === undefined) throw new Error(`record: ${symbol} is not recorded`);
      rows[at] = { ...row, state: "recording", started_at: startedAt };
    },
  };
}
