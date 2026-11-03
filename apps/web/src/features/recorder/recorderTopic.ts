/**
 * The recorder screen's reader of the WS `recorder` topic (23 §6.2.2, §15.8; E16-D02 §3.1; Q-04,
 * BQ-6, BQ-7), through the client's public surface only: `consume`, then `TopicHandle.read()` from
 * an animation frame, never per arrival (C9). Each `snap` or `d` is the whole status, never merged,
 * and is held only once it passes the generated `Recorder` shape; its envelope `ts` is the server's
 * clock (23 §4.2). The view is stale after 2 s without a frame (elapsed on a monotonic clock, so a
 * wall-clock step never hides it), at once while the socket is down (reconnecting or offline), and
 * after a reconnect until the next frame, which clears it. Nothing polls (Q-04): `onReread` asks the
 * page to re-read REST after a reconnect's first frame ("reconnect": the three first-paint reads),
 * and when the rows REST holds change (a row joining, leaving, leaving `starting` or reaching
 * `stopped`) or a write asks (`requestRows`: "rows", the list); every one at most once per 5 s with
 * one in flight, a held one read once the gap and the flight allow.
 */
import type { generated } from "@candleviewer/protocol";
import type { TopicFrame, WsClient } from "../../lib/ws/api";
import { getActiveClient } from "../../lib/ws/client/activeClient";

export type RecorderFrame = generated.ws.Recorder;
type Row = RecorderFrame["symbols"][number];
type Storage = NonNullable<RecorderFrame["storage"]>;
type Policy = NonNullable<RecorderFrame["policy"]>;
type Connection = NonNullable<RecorderFrame["connections"]>[number];

export const RECORDER_TOPIC = "recorder";
export const STALE_AFTER_MS = 2_000;
export const ROWS_REREAD_GAP_MS = 5_000;

type Check = (value: unknown) => boolean;
const isRecord = (value: unknown): value is Readonly<Record<string, unknown>> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const num: Check = (value) => typeof value === "number" && Number.isFinite(value);
const bool: Check = (value) => typeof value === "boolean";
const str: Check = (value) => typeof value === "string";
const orNull =
  (check: Check): Check =>
  (value) =>
    value === null || check(value);
/**
 * One of a generated union's values, named as the keys of `all`: a value added to or removed from the
 * union fails `typecheck` here, since the record must name each value exactly once (A-5309-12).
 */
const oneOf =
  <V extends string>(all: Readonly<Record<V, true>>): Check =>
  (value) =>
    typeof value === "string" && Object.hasOwn(all, value);
/** The same for a numeric union (`storage.level`): a number, never its text. */
const oneOfNumber =
  <V extends number>(all: Readonly<Record<V, true>>): Check =>
  (value) =>
    typeof value === "number" && Object.hasOwn(all, value);
const each = <K extends string>(keys: readonly K[], check: Check) =>
  Object.fromEntries(keys.map((key) => [key, check])) as Record<K, Check>;
const listOf =
  (check: Check): Check =>
  (value) =>
    Array.isArray(value) && value.every(check);
/**
 * Every field of `T` has a check, which a field present must pass; `required` must be present; a
 * field this build does not know passes (C-6.3).
 */
const shape =
  <T>(checks: { readonly [K in keyof T]-?: Check }, required: readonly (keyof T)[] = []): Check =>
  (value) =>
    isRecord(value) &&
    required.every((name) => Object.hasOwn(value, name)) &&
    Object.entries<Check>(checks).every(
      ([name, check]) => !Object.hasOwn(value, name) || check(value[name]),
    );

// prettier-ignore
const ROW = shape<Row>({
  ...each(["lag_ms", "rows_last_hour", "dropped_messages", "resyncs_last_hour", "disk_bytes", "last_event_at_ms"], num),
  ...each(["pinned", "lingering"], bool),
  symbol: str,
  state: oneOf<Row["state"]>({ idle: true, starting: true, recording: true, degraded: true, stopping: true, stopped: true, error: true }),
  reason: oneOf<NonNullable<Row["reason"]>>({ manual: true, chart_open: true, position_open: true, rule_dependency: true, alert_dependency: true }),
  linger_until_ms: orNull(num),
  refusal: orNull(str), // open-ended for readers (C-6.3): a value this build does not know passes
}, ["symbol", "state"]);
// prettier-ignore
const POLICY_NUMBERS = ["autostart_delay_s", "autostop_grace_s", "max_symbols", "warn_pct", "autostop_pct", "halt_pct"] as const;
// prettier-ignore
const STORAGE = shape<Storage>({
  ...each(["disk_free_bytes", "daily_growth_bytes", "cap_bytes", "used_bytes"], num),
  level: oneOfNumber<NonNullable<Storage["level"]>>({ 0: true, 1: true, 2: true, 3: true }),
  write_gate: oneOf<NonNullable<Storage["write_gate"]>>({ open: true, closed: true }),
  write_gate_reason: orNull(str), // open-ended for readers (C-6.3)
  accelerate_retention: bool,
  projected_full_at_ms: orNull(num),
});
// prettier-ignore
const CONNECTION = shape<Connection>({
  ...each(["subscribed_topics", "reconnects_last_hour", "last_ping_ms"], num),
  endpoint: str,
  state: oneOf<NonNullable<Connection["state"]>>({ connecting: true, connected: true, degraded: true, disconnected: true }),
});
// prettier-ignore
const FRAME = shape<RecorderFrame>({
  ...each(["ingest_rate_msgs_per_sec", "write_backlog_rows"], num),
  overall: oneOf<RecorderFrame["overall"]>({ healthy: true, degraded: true, warning: true, down: true }),
  role_restricted: bool,
  policy: shape<Policy>({ ...each(POLICY_NUMBERS, num), autorecord_enabled: bool }, [...POLICY_NUMBERS, "autorecord_enabled"]),
  connections: listOf(CONNECTION),
  symbols: listOf(ROW),
  storage: STORAGE,
}, ["overall", "symbols"]);

/** The shape check of a `recorder` payload (23 §15.8, the generated `Recorder`). */
export const isRecorderFrame = (value: unknown): value is RecorderFrame => FRAME(value);

/** The JSON payload of a `d`, or of a single-frame `snap` (a recorder status is never chunked). */
function payloadOf(frame: Exclude<TopicFrame, { kind: "reset" }>): unknown {
  const body =
    frame.kind === "d" ? frame.body : frame.bodies.length === 1 ? frame.bodies[0] : undefined;
  return body?.e === "j" ? body.p : undefined;
}

/**
 * The rows REST holds changed: a row (not a refused start) joined, left, left `starting` or reached
 * `stopped` (its session closed: the stopped row's words read it, A-5309-01).
 */
function rowsChanged(before: RecorderFrame, after: RecorderFrame): boolean {
  const was = new Map(before.symbols.map((row) => [row.symbol, row.state]));
  const listed = (frame: RecorderFrame): number =>
    frame.symbols.filter((row) => row.state !== "idle").length;
  return (
    listed(before) !== listed(after) ||
    after.symbols.some(({ symbol, state }) => {
      const prior = was.get(symbol);
      return (
        state !== "idle" &&
        (prior === undefined ||
          prior === "idle" ||
          (prior === "starting" && state !== "starting") ||
          (prior !== "stopped" && state === "stopped"))
      );
    })
  );
}

export interface RecorderTopicView {
  /** The newest frame that passed the shape check; null until one has. */
  readonly frame: RecorderFrame | null;
  /** When it was read, on the client's wall clock (epoch ms): the page's "updated" time. */
  readonly frameAtMs: number | null;
  /**
   * Its envelope `ts`, the server's send time (23 §4.2, epoch ms): the clock the server's times are read
   * against (a lingering deadline, a last write), so a skewed client clock never shifts them. Null until a
   * frame carries a usable one.
   */
  readonly serverMs: number | null;
  readonly stale: boolean;
}
export type RereadCause = "reconnect" | "rows";
export type RecorderTopicClient = Pick<WsClient, "consume" | "getState">;

export interface RecorderTopicOptions {
  /** Defaults to the shell's client; with none, nothing is read and the view turns stale. */
  readonly client?: RecorderTopicClient | null | undefined;
  /** BQ-6, BQ-7: re-read REST; a promise returned holds the next "rows" re-read till it settles. */
  readonly onReread?: ((cause: RereadCause) => unknown) | undefined;
  /** The wall clock: `frameAtMs`. */
  readonly now?: (() => number) | undefined;
  /** Elapsed time (the 2 s staleness, the 5 s gap): monotonic, `performance.now()` by default. */
  readonly monotonic?: (() => number) | undefined;
  readonly raf?: ((callback: (frameTimeMs: number) => void) => number) | undefined;
  readonly caf?: ((handle: number) => void) | undefined;
}

export interface RecorderTopic {
  /** A `useSyncExternalStore` pair: the view is referentially stable between changes. */
  getView(): RecorderTopicView;
  subscribe(listener: () => void): () => void;
  /** Asks for the list again (a write landed), through the same 5 s gap and one in flight (BQ-7). */
  requestRows(): void;
  /** Stops reading and releases the subscription; idempotent. */
  close(): void;
}

/** A usable envelope `ts`: an epoch in ms after 1970. */
const serverTime = (ts: number): number | null => (Number.isFinite(ts) && ts > 0 ? ts : null);

export function openRecorderTopic(options: RecorderTopicOptions = {}): RecorderTopic {
  const client = options.client === undefined ? getActiveClient() : options.client;
  const now = options.now ?? Date.now;
  const monotonic = options.monotonic ?? (() => performance.now());
  const raf = options.raf ?? ((callback) => requestAnimationFrame(callback));
  const caf = options.caf ?? ((handle) => cancelAnimationFrame(handle));
  const handle =
    client?.consume({ ch: RECORDER_TOPIC, paneId: RECORDER_TOPIC, priority: "focused" }) ?? null;
  const listeners = new Set<() => void>();
  const openedAt = monotonic();
  let view: RecorderTopicView = { frame: null, frameAtMs: null, serverMs: null, stale: false };
  /** When the held frame was read, on the monotonic clock. */
  let frameMono: number | null = null;
  let next: number | undefined;
  let closed = false;
  /** A reconnect since the last frame: stale until the next, which asks for the re-read. */
  let reconnected = false;
  /** The re-read the gap or the one in flight holds back; "reconnect" (the three) holds the list too. */
  let due: RereadCause | null = null;
  let rowsAt = openedAt; // the page's first-paint read is the latest
  let inFlight = 0;

  /** Called at once; in flight until what it returns settles. A throw is raised on its own. */
  function reread(cause: RereadCause): void {
    inFlight += 1;
    const done = (): void => void (inFlight -= 1);
    void new Promise((resolve) => resolve(options.onReread?.(cause))).then(
      done,
      (error: unknown) => {
        done();
        throw error;
      },
    );
  }

  function read(): void {
    const at = monotonic();
    const link = client?.getState().link.kind;
    const down = link === "reconnecting" || link === "offline";
    if (down) reconnected = true;
    let { frame, frameAtMs, serverMs } = view;
    let fresh = false;
    for (const item of handle?.read() ?? []) {
      if (item.kind === "reset") {
        if (item.reason === "reconnect") reconnected = true;
        continue;
      }
      const payload = payloadOf(item);
      if (!isRecorderFrame(payload)) continue; // the held frame stands
      if (frame !== null && rowsChanged(frame, payload)) due ??= "rows";
      frame = payload;
      frameAtMs = now();
      serverMs = serverTime(item.ts);
      frameMono = at;
      fresh = true;
    }
    if (fresh && !down && reconnected) {
      reconnected = false;
      due = "reconnect"; // its reads include the list
    }
    if (due !== null && inFlight === 0 && at - rowsAt >= ROWS_REREAD_GAP_MS) {
      const cause = due;
      due = null;
      rowsAt = at;
      reread(cause);
    }
    const stale = down || reconnected || at - (frameMono ?? openedAt) >= STALE_AFTER_MS;
    if (fresh || stale !== view.stale) {
      view = { frame, frameAtMs, serverMs, stale };
      for (const listener of [...listeners]) listener();
    }
  }

  function tick(): void {
    next = undefined;
    if (closed) return;
    try {
      read();
    } finally {
      // A listener that throws is raised on its own; the next frame still reads.
      if (!closed) next = raf(tick);
    }
  }

  next = raf(tick);
  return {
    getView: () => view,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    requestRows() {
      due ??= "rows";
    },
    close() {
      if (closed) return;
      closed = true;
      if (next !== undefined) caf(next);
      handle?.release();
      listeners.clear();
    },
  };
}
