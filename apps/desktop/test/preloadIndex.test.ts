import { describe, expect, it, vi, beforeEach } from "vitest";

const invokeMock = vi.fn().mockResolvedValue("ok");
const onMock = vi.fn();
const removeListenerMock = vi.fn();
const exposeInMainWorldMock = vi.fn();

vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld: exposeInMainWorldMock },
  ipcRenderer: { invoke: invokeMock, on: onMock, removeListener: removeListenerMock },
}));

describe("preload bridge", () => {
  beforeEach(() => {
    vi.resetModules();
    invokeMock.mockClear();
    onMock.mockClear();
    removeListenerMock.mockClear();
    exposeInMainWorldMock.mockClear();
  });

  it("exposes exactly window.cv with the six named methods, no generic invoke or on", async () => {
    await import("../src/preload/index");
    expect(exposeInMainWorldMock).toHaveBeenCalledTimes(1);
    const [name, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, unknown>];
    expect(name).toBe("cv");
    expect(Object.keys(cv).sort()).toEqual([
      "crashLogAppend",
      "gpuInfo",
      "gpuRetry",
      "keychainGetKekHandle",
      "onGpuCrashed",
      "updatesCheck",
    ]);
    expect(cv["ipcRenderer"]).toBeUndefined();
    expect(cv["invoke"]).toBeUndefined();
    expect(cv["on"]).toBeUndefined();
  });

  it("gpuInfo() invokes exactly the cv:gpu:info channel with no caller-supplied args", async () => {
    const preload = await import("../src/preload/index");
    void preload;
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, () => unknown>];
    await cv["gpuInfo"]?.();
    expect(invokeMock).toHaveBeenCalledWith("cv:gpu:info");
  });

  it("keychainGetKekHandle() invokes exactly the cv:keychain:getKekHandle channel", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, () => unknown>];
    await cv["keychainGetKekHandle"]?.();
    expect(invokeMock).toHaveBeenCalledWith("cv:keychain:getKekHandle");
  });

  it("updatesCheck() invokes exactly the cv:updates:check channel", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, () => unknown>];
    await cv["updatesCheck"]?.();
    expect(invokeMock).toHaveBeenCalledWith("cv:updates:check");
  });

  it("crashLogAppend() sends only a fresh, schema-checked copy on cv:crashLog:append", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, Append>];
    const entry = { timestampMs: 1, message: "boom", context: { correlationId: "c-1" } };
    await cv["crashLogAppend"]?.(entry);
    expect(invokeMock).toHaveBeenCalledTimes(1);
    expect(invokeMock).toHaveBeenCalledWith("cv:crashLog:append", entry);
    expect(invokeMock.mock.calls[0]?.[1]).not.toBe(entry);
  });

  it.each([
    ["an unknown key", { timestampMs: 1, message: "x", cookie: "a=b" }],
    ["a wrong type", { timestampMs: "1", message: "x" }],
    ["an oversized message", { timestampMs: 1, message: "x".repeat(4097) }],
    ["no object at all", "boom"],
  ])("crashLogAppend() refuses %s in preload, before any IPC", async (_label, entry) => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, Append>];
    await expect(cv["crashLogAppend"]?.(entry)).rejects.toThrow("Crash log entry refused");
    expect(invokeMock).not.toHaveBeenCalled();
  });

  it("gpuRetry() invokes exactly cv:gpu:retry and passes no caller-supplied argument", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, Append>];
    await cv["gpuRetry"]?.({ relaunchArgs: ["--disable-gpu-sandbox"] });
    expect(invokeMock.mock.calls).toEqual([["cv:gpu:retry"]]);
  });

  /** Subscribes a listener through window.cv.onGpuCrashed; returns what the preload wired. */
  async function subscribeGpuCrashes() {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, Subscribe>];
    const listener = vi.fn();
    const unsubscribe = cv["onGpuCrashed"]?.(listener);
    const [channel, forward] = (onMock.mock.calls[0] ?? []) as [string, Forward];
    return { listener, unsubscribe, channel, forward };
  }
  const CRASH = { crashedAtMs: 1, restartCount: 1, reason: "crashed" };
  const IPC_EVENT = { sender: { invoke: invokeMock } };

  it("onGpuCrashed() hands its listener a copy of the payload, never the IPC event", async () => {
    const { listener, channel, forward } = await subscribeGpuCrashes();
    expect([onMock.mock.calls.length, channel]).toEqual([1, "cv:gpu:crashed"]);
    forward(IPC_EVENT, CRASH);
    expect(listener.mock.calls).toEqual([[CRASH]]);
    expect(listener.mock.calls[0]?.[0]).not.toBe(CRASH);
  });

  it("onGpuCrashed() drops a payload that fails the check", async () => {
    const { listener, forward } = await subscribeGpuCrashes();
    forward(IPC_EVENT, { ...CRASH, reason: "C:\\drivers\\gpu.dll" });
    expect(listener).not.toHaveBeenCalled();
  });

  it("onGpuCrashed()'s unsubscribe removes the same forwarder from cv:gpu:crashed", async () => {
    const { unsubscribe, forward } = await subscribeGpuCrashes();
    unsubscribe?.();
    expect(removeListenerMock.mock.calls).toEqual([["cv:gpu:crashed", forward]]);
  });

  it("onGpuCrashed() refuses a listener that is not a function, before subscribing", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, Subscribe>];
    expect(() => cv["onGpuCrashed"]?.("cv:gpu:info")).toThrow(TypeError);
    expect(onMock).not.toHaveBeenCalled();
  });
});

type Append = (entry: unknown) => Promise<unknown>;
type Subscribe = (listener: unknown) => () => void;
type Forward = (event: unknown, payload: unknown) => void;
