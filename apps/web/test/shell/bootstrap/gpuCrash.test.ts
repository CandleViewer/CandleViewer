// E10-S04 (#306) slice 9c: SCR-159's GPU-crash feed, the desktop app's only (F15; the ruling of
// record on #306, BQ-9.1 to 9.4): the store, its analytics, the browser, the shell's start and stop.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CvBridge } from "../../../src/shell/ElectronShellAdapter.js";
import type { GpuCrash } from "../../../src/shell/ShellPort.js";
import { hostGpu, retryGpuNow, watchGpu } from "../../../src/shell/bootstrap/gpuCrash.js";
import { getShellState, resetShellState } from "../../../src/shell/bootstrap/store.js";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore.js";
import { startShell } from "../../../src/shell/startShell.js";
import { FakePort } from "../../lib/ws/support/fakePort";

const CRASH: GpuCrash = { crashedAtMs: 1_000, restartCount: 1, reason: "crashed" };
const listeners = new Set<(crash: GpuCrash) => void>();
const gpuRetry = vi.fn(async () => undefined);
const onGpuCrashed = (listener: (crash: GpuCrash) => void): (() => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const desktop = (cv: object): void =>
  void Object.defineProperty(window, "cv", { configurable: true, value: cv as CvBridge });
const emit = (crash: unknown): void => listeners.forEach((listener) => listener(crash as GpuCrash));
const events: unknown[] = [];
const listen = (e: Event): void => void events.push((e as CustomEvent).detail);
const started = () =>
  startShell({
    wsUrl: "wss://localhost/api/v1/ws",
    fetchImpl: vi.fn(async () => new Response("{}")),
    port: new FakePort(),
  });

beforeEach(() => {
  resetShellState();
  events.length = 0;
  gpuRetry.mockClear();
  window.addEventListener(THEME_ANALYTICS_EVENT, listen);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 401 })),
  ); // the refresh
});
afterEach(() => {
  window.removeEventListener(THEME_ANALYTICS_EVENT, listen);
  Reflect.deleteProperty(window, "cv");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  listeners.clear();
});

describe("SCR-159's GPU crashes, from the shell's start to its stop", () => {
  it("in the desktop app: each crash reaches the store, reported once by its reason class only", async () => {
    desktop({ onGpuCrashed, gpuRetry });
    const shell = started();
    expect(listeners.size).toBe(1);
    emit(CRASH);
    emit({ crashedAtMs: 2_000, restartCount: 2, reason: "oom" });
    expect(getShellState().gpuCrash).toEqual({
      crashedAtMs: 2_000,
      restartCount: 2,
      reason: "oom",
    });
    expect(events).toEqual([
      { name: "shell.gpu_unavailable", reason: "crashed" },
      { name: "shell.gpu_unavailable", reason: "oom" },
    ]);
    await retryGpuNow(); // the preload's own function: no Electron adapter in the renderer
    expect(gpuRetry).toHaveBeenCalledTimes(1);
    shell.stop();
    expect(listeners.size).toBe(0);
    await expect(retryGpuNow()).rejects.toThrow("not watching");
  });

  it("in a tab: nothing reports a crash and Retry is refused, so no page ever shows", async () => {
    const shell = started();
    const handler = vi.fn();
    hostGpu().onCrashed(handler)();
    await expect(retryGpuNow()).rejects.toThrow("not available in a browser tab");
    expect([handler.mock.calls, getShellState().gpuCrash, events]).toEqual([[], null, []]);
    shell.stop();
  });

  it("never stops the shell's start: a bridge without the GPU event leaves the page off", async () => {
    const said = vi.spyOn(console, "error").mockImplementation(() => undefined);
    desktop({});
    const shell = started();
    expect(getShellState().gpuCrash).toBeNull();
    expect(said).toHaveBeenCalledWith("watchGpu: the GPU-crash event could not be subscribed");
    await expect(retryGpuNow()).rejects.toThrow("not watching");
    shell.stop();
  });

  it("keeps a crash only in the preload's shape, two counts and a closed reason, as a copy", () => {
    desktop({ onGpuCrashed, gpuRetry });
    const shell = started();
    const bad = [null, [], { ...CRASH, restartCount: -1 }, { ...CRASH, crashedAtMs: 1.5 }];
    for (const payload of [...bad, { ...CRASH, reason: "exit 0xC0000005" }]) emit(payload);
    emit({ ...CRASH, reason: "constructor" }); // an inherited name is no reason
    expect([getShellState().gpuCrash, events]).toEqual([null, []]);
    emit({ ...CRASH, detail: "platform text" });
    expect(getShellState().gpuCrash).toEqual(CRASH); // the three fields alone
    shell.stop();
  });

  it("lets a restarted shell's Retry reach its own port, not a try the last one left open", async () => {
    let refuse: (reason: Error) => void = () => undefined;
    let asked = (): void => undefined;
    const ask = (): Promise<void> => {
      asked();
      return new Promise<void>((_, reject) => (refuse = reject));
    };
    const none = (): (() => void) => () => undefined;
    const reached = new Promise<void>((resolve) => (asked = resolve));
    const stop = watchGpu({ onCrashed: none, retry: ask });
    const open = retryGpuNow();
    await reached;
    const refuseOld = refuse;
    stop();
    const reachedAgain = new Promise<void>((resolve) => (asked = resolve));
    const again = watchGpu({ onCrashed: none, retry: ask });
    const next = retryGpuNow();
    expect(next).not.toBe(open);
    await reachedAgain; // its own port was asked
    refuseOld(new Error("GPU retry refused")); // the old try ends late
    await open.catch(() => undefined);
    expect(retryGpuNow()).toBe(next); // and leaves the new one alone: one try at a time
    again();
  });
});
