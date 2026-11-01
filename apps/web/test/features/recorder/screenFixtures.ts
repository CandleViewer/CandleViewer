/**
 * E16-S01, SCR-140's page fixtures: E16-D02 §1's sample set (board 01 `running`; illustrative values, not a
 * capture) as the three first-paint answers and a `recorder` frame, a fetch router over them, and a fake socket
 * whose animation frame the test steps (the topic reads on rAF only, `recorderTopic.ts`).
 */
import { vi } from "vitest";
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../../src/lib/ws/api";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";
import type { Link } from "../../../src/lib/ws/state/types";
import type {
  RecordedSymbol,
  RecorderFrame,
  RecordingStatus,
  StorageUsage,
} from "../../../src/features/recorder/model";
import type { RecorderDataOptions } from "../../../src/features/recorder/useRecorderData";
import { NOW } from "./gridFixtures";
import { POLICY } from "./modelFixtures";

type FrameRow = RecorderFrame["symbols"][number];
type Storage = NonNullable<RecorderFrame["storage"]>;

const listed = (symbol: string, patch: Partial<RecordedSymbol> = {}): RecordedSymbol => ({
  id: `id-${symbol.toLowerCase()}`,
  symbol,
  reason: "manual",
  state: "recording",
  pinned: false,
  depth: 200,
  retention_days: 30,
  started_at: "2026-09-01T09:00:00Z",
  streams: ["trades", "orderbook_delta", "tickers", "liquidations"],
  ...patch,
});

/** `listRecordedSymbols`: D02 §1's five rows (BTC pinned, SOL by its chart, XRP by a position, ADA stopped). */
export const LIST: readonly RecordedSymbol[] = [
  listed("BTCUSDT", { pinned: true, retention_days: null, disk_bytes: 34.8e9 }),
  listed("ETHUSDT", { started_at: "2026-09-04T08:00:00Z", disk_bytes: 15.6e9 }),
  listed("SOLUSDT", {
    reason: "chart_open",
    refusal: "chart_open",
    started_at: "2026-09-14T10:14:00Z",
    depth: 50,
    disk_bytes: 1.3e6,
  }),
  listed("XRPUSDT", {
    reason: "position_open",
    refusal: "position_open",
    started_at: "2026-09-14T09:02:00Z",
    disk_bytes: 6.9e6,
  }),
  listed("ADAUSDT", { state: "stopped", started_at: "2026-09-10T07:00:00Z", disk_bytes: 11.0e9 }),
];

export const STATUS: RecordingStatus = {
  overall: "healthy",
  policy: POLICY,
  symbols: LIST.map((row) => ({ symbol: row.symbol, state: row.state, dropped_messages: 0 })),
  generated_at: new Date(NOW).toISOString(),
};

/** `getStorageUsage`: D02 §3 `running`, a 200 GB budget, 61.4 GB used, 0.93 GB a day. */
export const STORAGE: StorageUsage = {
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
  symbols: [
    { symbol: "BTCUSDT", used_bytes: 34.8e9, daily_growth_bytes: 0.71e9, pinned: true },
    { symbol: "ETHUSDT", used_bytes: 15.6e9, daily_growth_bytes: 0.52e9, pinned: false },
  ],
};

const live = (row: RecordedSymbol, patch: Partial<FrameRow> = {}): FrameRow => ({
  symbol: row.symbol,
  state: row.state,
  reason: row.reason,
  pinned: row.pinned ?? false,
  ...(row.refusal == null ? {} : { refusal: row.refusal }),
  ...(row.disk_bytes === undefined ? {} : { disk_bytes: row.disk_bytes }),
  dropped_messages: 0,
  last_event_at_ms: NOW - 1_000,
  ...patch,
});

/** A `recorder` frame over `LIST`, each row patched by symbol, and the storage patched. */
export function frameOf(
  rows: Readonly<Record<string, Partial<FrameRow>>> = {},
  storage: Partial<Storage> = {},
): RecorderFrame {
  return {
    overall: "healthy",
    policy: POLICY,
    symbols: LIST.map((row) => live(row, rows[row.symbol])),
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
      ...storage,
    },
  };
}

type Route = (method: string, url: string) => Response | null | undefined;
const json = (status: number, body?: unknown): Response =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });

/** The answers by path; `override` answers first (return `undefined` to fall through). */
export function router(override: Route = () => undefined) {
  return async (url: string, init?: RequestInit): Promise<Response> => {
    const method = init?.method ?? "GET";
    const first = override(method, url);
    if (first !== undefined && first !== null) return first;
    const path = url.replace("/api/v1", "");
    if (path.startsWith("/recording/symbols") && method === "GET") {
      return json(200, { items: LIST, meta: { count: LIST.length, has_more: false } });
    }
    if (path === "/recording/status") return json(200, STATUS);
    if (path === "/recording/storage") return json(200, STORAGE);
    if (path.startsWith("/recording/sessions")) {
      const items = [{ symbol: "ADAUSDT", ended_at: "2026-09-12T09:00:00Z", state: "stopped" }];
      return json(200, { items, meta: { count: 1, has_more: false } });
    }
    if (path.startsWith("/market/data-coverage")) {
      const symbol = new URL(`http://x${path}`).searchParams.get("symbol");
      return json(200, { symbol, streams: [] });
    }
    return json(404, { code: "not_found", status: 404, title: "Not found", type: "about:blank" });
  };
}

const STAMP = { seq: 1, ts: 0, sp: undefined, decodeMs: 0, size: 1, meta: undefined };

/**
 * A fake socket for the page's topic: `push` queues a frame (`ts`, its envelope's server send time, 0 for none),
 * `step` advances the page's clock and runs the animation frame (where the topic reads), `link` sets the socket's
 * state. The topic's monotonic clock is the page's clock too.
 */
export function fakeSocket(clock: { now: number }) {
  const queue: TopicFrame[] = [];
  let link: Link = { kind: "up" };
  let pending: ((t: number) => void) | undefined;
  const handle: TopicHandle = {
    ch: "recorder",
    read: () => queue.splice(0),
    effective: {},
    status: "live",
    source: "live",
    rs: undefined,
    release: vi.fn(),
  };
  const client = {
    consume: vi.fn<(spec: ConsumerSpec) => TopicHandle>(() => handle),
    getState: () => ({ ...INITIAL_WS_STATE, link }),
  };
  const options: RecorderDataOptions = {
    topic: {
      client,
      now: () => clock.now,
      monotonic: () => clock.now,
      raf: (callback) => {
        pending = callback;
        return 1;
      },
      caf: () => {
        pending = undefined;
      },
    },
    now: () => clock.now,
  };
  return {
    options,
    handle,
    push(frame: RecorderFrame, ts = 0): void {
      queue.push({ ...STAMP, ts, kind: "d", body: { e: "j", p: frame } });
    },
    /** Runs the pending animation frame `ms` later. */
    step(ms = 1_000): void {
      clock.now += ms;
      const run = pending;
      pending = undefined;
      run?.(clock.now);
    },
    link(next: Link): void {
      link = next;
    },
  };
}
