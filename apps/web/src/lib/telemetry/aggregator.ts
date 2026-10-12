/**
 * Frontend telemetry aggregator (E04-T06, ADR-0014 §2).
 *
 * Pre-buckets samples locally (histogram-of-histograms; raw samples never
 * leave the client) and pushes one payload per 10 s to
 * `POST /api/v1/telemetry/frontend`. Telemetry must never harm the app:
 * a failed push drops the batch after ONE attempt (no retry, no queue), and
 * every error is swallowed — nothing user-visible, never a retry storm
 * against a degraded backend. Memory is O(buckets): a fixed set of counters.
 */

import type { generated } from "@candleviewer/protocol";
import { apiFetch } from "../http/csrfFetch";

/** Bucket edges in ms; must match `22-api-openapi.yaml` FrontendTelemetry. */
export const FRAME_EDGES_MS = [4, 8, 12, 16, 20, 33, 50, 100] as const;
export const DECODE_EDGES_MS = [0.1, 0.25, 0.5, 1, 2, 4, 5, 10] as const;
export const PUSH_INTERVAL_MS = 10_000;
/** Server-side per-bucket cap per window; we clamp to it. */
const MAX_COUNT = 2400;

/** The generated `postFrontendTelemetry` request body (`packages/protocol`). */
export type TelemetryPayload =
  generated.rest.operations["postFrontendTelemetry"]["requestBody"]["content"]["application/json"];

export type Transport = (payload: TelemetryPayload) => Promise<unknown>;

const SCREEN_RE = /^R-[0-9]{3}$/;

function bucketIndex(edges: readonly number[], value: number): number {
  for (let i = 0; i < edges.length; i += 1) {
    if (value <= (edges[i] ?? Infinity)) return i;
  }
  return edges.length;
}

export class TelemetryAggregator {
  private frame: number[] = new Array<number>(FRAME_EDGES_MS.length + 1).fill(0);
  private decode: number[] = new Array<number>(DECODE_EDGES_MS.length + 1).fill(0);
  private dropped = 0;
  private gpuMb: number | undefined;
  private screen = "R-100";
  private inFlight = false;

  constructor(
    private readonly transport: Transport,
    private readonly engineVersion: string,
  ) {}

  /** Route id from the sitemap manifest; free-form paths are ignored. */
  setScreen(routeId: string): void {
    if (SCREEN_RE.test(routeId)) this.screen = routeId;
  }

  recordFrame(ms: number): void {
    const i = bucketIndex(FRAME_EDGES_MS, ms);
    this.frame[i] = Math.min(MAX_COUNT, (this.frame[i] ?? 0) + 1);
  }

  recordDecode(ms: number): void {
    const i = bucketIndex(DECODE_EDGES_MS, ms);
    this.decode[i] = Math.min(MAX_COUNT, (this.decode[i] ?? 0) + 1);
  }

  recordDroppedFrames(n: number): void {
    this.dropped = Math.min(MAX_COUNT, this.dropped + Math.max(0, Math.floor(n)));
  }

  setGpuMemoryMb(mb: number): void {
    if (Number.isFinite(mb) && mb >= 0) this.gpuMb = Math.min(65536, mb);
  }

  /** Snapshot and reset. Returns `null` when there is nothing to send. */
  drain(): TelemetryPayload | null {
    const empty =
      this.frame.every((c) => c === 0) && this.decode.every((c) => c === 0) && this.dropped === 0;
    const payload: TelemetryPayload = {
      screen: this.screen,
      engine_version: this.engineVersion,
      fe_frame_time_ms: { counts: this.frame },
      fe_ws_decode_ms: { counts: this.decode },
      fe_dropped_frames_total: this.dropped,
      ...(this.gpuMb === undefined ? {} : { fe_gpu_memory_mb: this.gpuMb }),
    };
    this.frame = new Array<number>(FRAME_EDGES_MS.length + 1).fill(0);
    this.decode = new Array<number>(DECODE_EDGES_MS.length + 1).fill(0);
    this.dropped = 0;
    return empty ? null : payload;
  }

  /**
   * One push attempt. The batch is drained *before* sending, so a failure
   * simply loses it; overlapping flushes are skipped (at most one in flight).
   * Never throws.
   */
  async flush(): Promise<boolean> {
    if (this.inFlight) {
      this.drain();
      return false;
    }
    const payload = this.drain();
    if (payload === null) return false;
    this.inFlight = true;
    try {
      await this.transport(payload);
      return true;
    } catch {
      return false;
    } finally {
      this.inFlight = false;
    }
  }

  /** Start the 10 s push loop; returns the teardown. */
  start(
    schedule: typeof setInterval = setInterval,
    cancel: typeof clearInterval = clearInterval,
  ): () => void {
    const handle = schedule(() => {
      void this.flush();
    }, PUSH_INTERVAL_MS);
    return () => cancel(handle);
  }
}

/** Default transport: same-origin, credentialed, single attempt, 5 s timeout. */
export function fetchTransport(baseUrl = "/api/v1"): Transport {
  return async (payload) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5_000);
    try {
      const res = await apiFetch(`${baseUrl}${TELEMETRY_PATH}`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
        keepalive: true,
      });
      if (!res.ok) throw new Error(`telemetry ${res.status}`);
      return res;
    } finally {
      clearTimeout(timer);
    }
  };
}

/** Generated-contract path for `postFrontendTelemetry`. */
export const TELEMETRY_PATH: keyof generated.rest.paths = "/telemetry/frontend";

/**
 * App-level start (called once from `App` on mount): one aggregator, one
 * bounded 10 s push loop (the only network rate). Returns the teardown.
 */
export function startTelemetry(
  transport: Transport = fetchTransport(),
  engineVersion = "0.1.0",
): { readonly aggregator: TelemetryAggregator; stop(): void } {
  const aggregator = new TelemetryAggregator(transport, engineVersion);
  const stop = aggregator.start();
  return { aggregator, stop };
}
