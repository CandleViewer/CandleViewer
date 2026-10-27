import { describe, expect, it, vi, type Mock } from "vitest";
import {
  DECODE_EDGES_MS,
  FRAME_EDGES_MS,
  PUSH_INTERVAL_MS,
  TelemetryAggregator,
  fetchTransport,
  recordDecode,
  type TelemetryPayload,
  TELEMETRY_PATH,
  startTelemetry,
  type Transport,
} from "../../../src/lib/telemetry/aggregator";
import { throttleIndicator, toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator";

type TransportMock = Mock<(p: TelemetryPayload) => Promise<unknown>>;

function agg(transport: Transport = vi.fn().mockResolvedValue(undefined)) {
  return { a: new TelemetryAggregator(transport, "0.1.0"), transport: transport as TransportMock };
}

describe("TelemetryAggregator", () => {
  it("pre-buckets samples on the contract edges (no raw samples)", () => {
    const { a } = agg();
    a.recordFrame(3);
    a.recordFrame(16);
    a.recordFrame(500);
    a.recordDecode(0.05);
    a.recordDroppedFrames(2);
    a.setGpuMemoryMb(128);
    const p = a.drain();
    expect(p?.fe_frame_time_ms.counts).toHaveLength(FRAME_EDGES_MS.length + 1);
    expect(p?.fe_frame_time_ms.counts).toEqual([1, 0, 0, 1, 0, 0, 0, 0, 1]);
    expect(p?.fe_ws_decode_ms.counts).toHaveLength(DECODE_EDGES_MS.length + 1);
    expect(p?.fe_ws_decode_ms.counts[0]).toBe(1);
    expect(p?.fe_dropped_frames_total).toBe(2);
    expect(p?.fe_gpu_memory_mb).toBe(128);
    expect(a.drain()).toBeNull();
  });

  it("only accepts sitemap route ids as screen", () => {
    const { a } = agg();
    a.setScreen("/terminal/abc");
    a.recordFrame(1);
    expect(a.drain()?.screen).toBe("R-100");
    a.setScreen("R-300");
    a.recordFrame(1);
    expect(a.drain()?.screen).toBe("R-300");
  });

  it("caps counts so memory and payload stay bounded", () => {
    const { a } = agg();
    for (let i = 0; i < 5000; i += 1) a.recordFrame(1);
    a.recordDroppedFrames(1e9);
    const p = a.drain();
    expect(p?.fe_frame_time_ms.counts[0]).toBe(2400);
    expect(p?.fe_dropped_frames_total).toBe(2400);
  });

  it("drops the batch after one failed attempt when the backend is unreachable", async () => {
    const transport = vi
      .fn<(p: TelemetryPayload) => Promise<unknown>>()
      .mockRejectedValue(new TypeError("offline"));
    const { a } = agg(transport);
    a.recordFrame(5);
    await expect(a.flush()).resolves.toBe(false);
    expect(transport).toHaveBeenCalledTimes(1);
    // Nothing queued for retry.
    await expect(a.flush()).resolves.toBe(false);
    expect(transport).toHaveBeenCalledTimes(1);
  });

  it("never has more than one push in flight and does not queue", async () => {
    let release: () => void = () => undefined;
    const transport = vi.fn<(p: TelemetryPayload) => Promise<unknown>>(
      () => new Promise((r) => (release = () => r(undefined))),
    );
    const { a } = agg(transport);
    a.recordFrame(5);
    const first = a.flush();
    a.recordFrame(5);
    await expect(a.flush()).resolves.toBe(false);
    release();
    await expect(first).resolves.toBe(true);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(a.drain()).toBeNull();
  });

  it("pushes every 10 s and tears down", () => {
    vi.useFakeTimers();
    const { a, transport } = agg();
    const stop = a.start();
    a.recordFrame(5);
    vi.advanceTimersByTime(PUSH_INTERVAL_MS);
    expect(transport).toHaveBeenCalledTimes(1);
    stop();
    a.recordFrame(5);
    vi.advanceTimersByTime(PUSH_INTERVAL_MS * 3);
    expect(transport).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});

describe("fetchTransport", () => {
  it("posts once, credentialed, and rejects on non-2xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 429 });
    vi.stubGlobal("fetch", fetchMock);
    const { a } = agg(fetchTransport());
    a.recordFrame(5);
    await expect(a.flush()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/telemetry/frontend");
    expect(init.credentials).toBe("include");
    fetchMock.mockResolvedValue({ ok: true, status: 204 });
    a.recordFrame(5);
    await expect(a.flush()).resolves.toBe(true);
    vi.unstubAllGlobals();
  });
});

describe("latency indicator contract", () => {
  it("supplies value, unit and a state word", () => {
    expect(toLatencyIndicator(38.4)).toEqual({
      valueMs: 38,
      unit: "ms",
      state: "ok",
      label: "WS latency: ok, 38 ms",
    });
    expect(toLatencyIndicator(150).state).toBe("degraded");
    expect(toLatencyIndicator(300).state).toBe("breach");
    expect(toLatencyIndicator(null).label).toBe("WS latency: unavailable");
    expect(toLatencyIndicator(-5).state).toBe("unavailable");
  });

  it("throttles updates to at most 1 Hz", () => {
    let t = 0;
    const emit = vi.fn();
    const push = throttleIndicator(emit, () => t);
    for (let i = 0; i < 20; i += 1) {
      push(40);
      t += 100;
    }
    expect(emit).toHaveBeenCalledTimes(2);
  });
});

describe("startTelemetry", () => {
  it("posts one bounded payload per interval to the contract path and stops cleanly", async () => {
    vi.useFakeTimers();
    const sent: unknown[] = [];
    const { aggregator, stop } = startTelemetry(async (p) => {
      sent.push(p);
    });
    aggregator.recordFrame(10);
    await vi.advanceTimersByTimeAsync(PUSH_INTERVAL_MS);
    expect(sent).toHaveLength(1);
    stop();
    aggregator.recordFrame(10);
    await vi.advanceTimersByTimeAsync(PUSH_INTERVAL_MS * 3);
    expect(sent).toHaveLength(1);
    expect(TELEMETRY_PATH).toBe("/telemetry/frontend");
    vi.useRealTimers();
  });

  it("recordDecode feeds the started aggregator, the latest one, and none once it is stopped", () => {
    const decoded = (a: TelemetryAggregator) => a.drain()?.fe_ws_decode_ms.counts ?? [];
    recordDecode(1); // none started: dropped
    const first = startTelemetry(async () => undefined);
    const second = startTelemetry(async () => undefined);
    recordDecode(1);
    expect(decoded(first.aggregator)).toEqual([]);
    expect(decoded(second.aggregator)).toEqual([0, 0, 0, 1, 0, 0, 0, 0, 0]); // the 1 ms bucket
    first.stop(); // not the one fed: the feed stays
    recordDecode(1);
    expect(decoded(second.aggregator)).toEqual([0, 0, 0, 1, 0, 0, 0, 0, 0]);
    second.stop();
    recordDecode(1);
    expect(decoded(second.aggregator)).toEqual([]);
  });
});
