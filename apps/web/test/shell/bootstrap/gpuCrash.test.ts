// E10-S04 (#306) slice 9c: SCR-159's GPU-crash feed, the desktop app's only (F15; the ruling of
// record on #306, BQ-9.1 to 9.4): the store, its analytics, the browser, the shell's start and stop.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CvBridge } from "../../../src/shell/ElectronShellAdapter.js";
import type * as ElectronAdapterModule from "../../../src/shell/ElectronShellAdapter.js";
import type { GpuCrash, GpuInfo, GpuLastCrash, ShellPort } from "../../../src/shell/ShellPort.js";
import { retryGpuNow, watchGpu } from "../../../src/shell/bootstrap/gpuCrash.js";
import {
  getShellState,
  keepSoftwareRendering,
  resetShellState,
} from "../../../src/shell/bootstrap/store.js";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore.js";
import { startShell } from "../../../src/shell/startShell.js";
import { FakePort } from "../../lib/ws/support/fakePort";

// The Electron adapters made and their GPU calls, in order: the shell port's pick where the preload ran.
const viaAdapter = vi.hoisted((): string[] => []);
vi.mock("../../../src/shell/ElectronShellAdapter.js", async (importOriginal) => {
  const real = await importOriginal<typeof ElectronAdapterModule>();
  const createElectronShellAdapter = (): ShellPort => {
    const port = real.createElectronShellAdapter();
    const { onCrashed, retry } = port.gpu;
    viaAdapter.push("created");
    const gpu: ShellPort["gpu"] = {
      ...port.gpu,
      onCrashed: (handler) => {
        viaAdapter.push("onCrashed");
        return onCrashed(handler);
      },
      retry: () => {
        viaAdapter.push("retry");
        return retry();
      },
    };
    return { ...port, gpu };
  };
  return { ...real, createElectronShellAdapter };
});

const CRASH: GpuCrash = { crashedAtMs: 1_000, restartCount: 1, reason: "crashed" };
const listeners = new Set<(crash: GpuCrash) => void>();
const gpuRetry = vi.fn(async () => undefined);
const onGpuCrashed = (listener: (crash: GpuCrash) => void): (() => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const INFO = {
  vendor: "v",
  renderer: "r",
  hardwareAccelerated: true,
  webgl2CapabilityParity: true,
};
/** cv:gpu:info where a test's bridge names none: main answers no crash this session. */
const NO_CRASH: Partial<CvBridge> = { gpuInfo: async () => ({ ...INFO, lastCrash: null }) };
const desktop = (cv: object): void =>
  void Object.defineProperty(window, "cv", { configurable: true, value: { ...NO_CRASH, ...cv } });
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
  viaAdapter.length = 0;
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
    await retryGpuNow(); // the preload's own function, through the Electron adapter
    expect(gpuRetry).toHaveBeenCalledTimes(1);
    shell.stop();
    expect(listeners.size).toBe(0);
    await expect(retryGpuNow()).rejects.toThrow("not watching");
  });

  it("in a tab: nothing reports a crash and Retry is refused, so no page ever shows", async () => {
    const probe = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    const shell = started();
    await expect(retryGpuNow()).rejects.toThrow("not available in a browser tab");
    expect([viaAdapter, getShellState().gpuCrash, events]).toEqual([[], null, []]); // the tab's port
    expect(probe).not.toHaveBeenCalled(); // no crash to read: no WebGL probe at the start (#4951)
    shell.stop();
  });

  it("reads the desktop's GPU through the Electron adapter, the shell port where the preload ran", async () => {
    desktop({ onGpuCrashed, gpuRetry });
    const shell = started();
    await retryGpuNow();
    expect([viaAdapter, gpuRetry.mock.calls.length]).toEqual([
      ["created", "onCrashed", "retry"],
      1,
    ]);
    shell.stop();
  });

  it("watches the port it is given, not the shell's: a test's fake, though the preload ran", async () => {
    desktop({ onGpuCrashed, gpuRetry });
    const retry = vi.fn(async () => undefined);
    const stop = watchGpu({ onCrashed: () => () => undefined, retry });
    await retryGpuNow();
    stop();
    expect([retry.mock.calls.length, viaAdapter, gpuRetry.mock.calls.length]).toEqual([1, [], 0]);
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

// #4951: a crash before the watcher subscribed (at boot, or during a reload) is cv:gpu:info's
// lastCrash, read once when the Electron adapter's gpu.onCrashed subscribes.
describe("SCR-159's GPU crash from before the shell's start (cv:gpu:info's lastCrash)", () => {
  const REPORTED = { name: "shell.gpu_unavailable", reason: "crashed" };
  const READ_FAILED = "gpu.onCrashed: the last-crash read failed";
  const answering = (lastCrash: GpuLastCrash | null) =>
    vi.fn(async (): Promise<GpuInfo> => ({ ...INFO, lastCrash }));
  /** A pull that main answers when the test says. */
  function held() {
    let resolveInfo: (info: GpuInfo) => void = () => undefined;
    const gpuInfo = vi.fn(() => new Promise<GpuInfo>((resolve) => (resolveInfo = resolve)));
    return { gpuInfo, answer: (info: GpuInfo) => resolveInfo(info) };
  }

  it("shows it once, read as the watcher subscribes; main's push of the same crash adds nothing", async () => {
    const gpuInfo = answering({ ...CRASH, retried: false });
    desktop({ onGpuCrashed, gpuRetry, gpuInfo });
    const shell = started();
    expect(gpuInfo).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(getShellState().gpuCrash).toEqual(CRASH));
    emit(CRASH);
    expect(events).toEqual([REPORTED]);
    emit({ ...CRASH, crashedAtMs: 2_000, restartCount: 2 }); // a newer crash is a page of its own
    expect(events).toEqual([REPORTED, REPORTED]);
    shell.stop();
  });

  it.each([
    ["the same crash", CRASH],
    ["a newer crash", { ...CRASH, crashedAtMs: 2_000, restartCount: 2 }],
  ])("keeps %s pushed before the pull's answer, reported once", async (_label, pushed) => {
    const { gpuInfo, answer } = held();
    desktop({ onGpuCrashed, gpuRetry, gpuInfo });
    const shell = started();
    emit(pushed);
    answer({ ...INFO, lastCrash: { ...CRASH, retried: false } }); // older than a newer `pushed`
    await gpuInfo.mock.results[0]?.value;
    expect([gpuInfo.mock.calls.length, getShellState().gpuCrash, events]).toEqual([
      1,
      pushed,
      [REPORTED],
    ]);
    shell.stop();
  });

  it.each([
    ["a crash a retry answered (the relaunch is under way)", { ...CRASH, retried: true }],
    ["no crash this session (a relaunched one)", null],
  ])("shows nothing for %s", async (_label, lastCrash) => {
    const gpuInfo = answering(lastCrash);
    desktop({ onGpuCrashed, gpuRetry, gpuInfo });
    const shell = started();
    await gpuInfo.mock.results[0]?.value;
    expect([gpuInfo.mock.calls.length, getShellState().gpuCrash, events]).toEqual([1, null, []]);
    shell.stop();
  });

  it("a refused read shows nothing and logs one fixed line, with no payload", async () => {
    const said = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const gpuInfo = vi.fn(async (): Promise<GpuInfo> => Promise.reject(new Error("refused")));
    desktop({ onGpuCrashed, gpuRetry, gpuInfo });
    const shell = started();
    await vi.waitFor(() => expect(said).toHaveBeenCalledWith(READ_FAILED));
    const logged = said.mock.calls.filter((call) => call.includes(READ_FAILED));
    expect([logged, getShellState().gpuCrash, events]).toEqual([[[READ_FAILED]], null, []]);
    shell.stop();
  });

  it("drops an answer that comes after the shell stopped", async () => {
    const { gpuInfo, answer } = held();
    desktop({ onGpuCrashed, gpuRetry, gpuInfo });
    started().stop();
    answer({ ...INFO, lastCrash: { ...CRASH, retried: false } });
    await gpuInfo.mock.results[0]?.value;
    expect([gpuInfo.mock.calls.length, getShellState().gpuCrash, events]).toEqual([1, null, []]);
  });

  it("holds SCR-153's GPU row, not the page, for a crash the user kept software rendering for", async () => {
    const gpuInfo = answering({ ...CRASH, retried: false });
    desktop({ onGpuCrashed, gpuRetry, gpuInfo });
    const first = started();
    await vi.waitFor(() => expect(getShellState().gpuCrash).toEqual(CRASH));
    keepSoftwareRendering();
    first.stop(); // its degraded facts go with it
    const again = started(); // a restarted shell reads the same crash
    await gpuInfo.mock.results[1]?.value;
    emit(CRASH); // and its push, while the row holds: asserted once, so a dismissed row stays gone
    expect(getShellState().gpuCrash).toBeNull();
    expect(getShellState().degraded.asserted.gpuFallback).toBe(1);
    expect(events).toEqual([REPORTED]);
    again.stop();
  });
});
