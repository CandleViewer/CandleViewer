// E11-S15 PR-1: the MemoryAccount registry (26 §7, BQ-S15-01) and its live sources in the runtime:
// the GL buffers and textures and the default framebuffer register at init; the stores join when
// their owners wire them (E12-S06 bars, E18 footprint, E21 heatmap).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryAccount } from "../../src/memory/index.js";
import { BAR_BYTES } from "../../src/model/BarStore.js";
import { BarStore } from "../../src/model/index.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap } from "../interaction/fixtures.js";
import { bars } from "../model/fixtures.js";

describe("MemoryAccount", () => {
  it("sums its sources, replaces a re-registered id and removes on unregister", () => {
    const account = new MemoryAccount();
    let gl = 1024;
    const off = account.register({ id: "gl", bytes: () => gl });
    account.register({ id: "framebuffer", bytes: () => 2 ** 20 });
    expect([account.totalBytes, account.usedMb]).toEqual([2 ** 20 + 1024, 1 + 1 / 1024]);
    gl = 0;
    account.register({ id: "framebuffer", bytes: () => 2 * 2 ** 20 }); // replaces, not doubles
    expect([account.ids, account.usedMb]).toEqual([["gl", "framebuffer"], 2]);
    off();
    off(); // idempotent
    expect([account.ids, account.unregister("gl"), account.unregister("framebuffer")]).toEqual([
      ["framebuffer"],
      false,
      true,
    ]);
    expect(account.totalBytes).toBe(0);
  });

  it("counts a real store's bytes, and a broken source as 0, never NaN or negative", () => {
    const account = new MemoryAccount();
    const store = new BarStore();
    account.register({ id: "bars", bytes: () => store.bytes });
    account.register({ id: "nan", bytes: () => Number.NaN });
    account.register({ id: "neg", bytes: () => -5 });
    store.append(bars(0, 43_200));
    expect(account.totalBytes).toBe(65_536 * BAR_BYTES);
  });
});

describe("Scenario: the runtime registers the live sources at init (BQ-S15-01)", () => {
  let rt: RenderRuntime;
  let canvas: { width: number; height: number; getContext(): FakeGl };

  beforeEach(() => {
    vi.useFakeTimers();
    const gl = new FakeGl({ params: ROOMY });
    rt = createRenderRuntime({
      runMode: "inline",
      post: () => undefined,
      requestFrame: (cb) => void setTimeout(cb, 16),
      now: () => Number(vi.getMockedSystemTime()),
      setTimer: (cb, ms) => void setTimeout(cb, ms),
      probe: () => FULL,
      timeMap: minuteMap(),
    });
    canvas = { width: 400, height: 200, getContext: () => gl };
    rt.handle({
      t: "init",
      id: 1,
      canvas,
      dpr: 1,
      theme: {},
      config: { bench: true, syncGroup: null },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("charges nothing before a context opens, then GL plus the backing store", () => {
    const account = rt.memoryAccount(1);
    expect([account?.ids, account?.totalBytes]).toEqual([["gl", "framebuffer"], 0]);
    vi.advanceTimersByTime(16); // the first frame opens the backend
    const gl = account!.totalBytes - 400 * 200 * 4;
    expect(gl).toBeGreaterThanOrEqual(0);
    rt.handle({ t: "resize", id: 1, width: 800, height: 400, dpr: 1 });
    expect(account!.totalBytes - gl).toBe(800 * 400 * 4);
    expect(rt.memoryAccount(2)).toBeUndefined();
  });

  it("keeps a joined store across the degraded-2d re-init and re-points the live sources", () => {
    const account = rt.memoryAccount(1)!;
    account.register({ id: "bars", bytes: () => 4096 });
    const fresh = { width: 10, height: 10, getContext: () => new FakeGl({ params: ROOMY }) };
    rt.handle({
      t: "init",
      id: 1,
      canvas: fresh,
      dpr: 1,
      theme: {},
      config: { bench: true, syncGroup: null },
    });
    vi.advanceTimersByTime(16);
    expect(rt.memoryAccount(1)).toBe(account);
    expect(account.ids).toEqual(["bars", "gl", "framebuffer"]);
    expect(account.totalBytes).toBeGreaterThanOrEqual(4096 + 10 * 10 * 4);
  });
});
