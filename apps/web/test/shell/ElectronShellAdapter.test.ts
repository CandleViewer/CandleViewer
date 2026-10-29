import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ELECTRON_CAPABILITIES,
  createElectronShellAdapter,
  type CvBridge,
} from "../../src/shell/ElectronShellAdapter.js";

function makeStubBridge(): CvBridge {
  return {
    windowsFloat: vi.fn().mockResolvedValue(undefined),
    windowsRedock: vi.fn().mockResolvedValue(undefined),
    windowsSaveState: vi.fn().mockResolvedValue(undefined),
    windowsRestoreState: vi.fn().mockResolvedValue([]),
    traySetStatus: vi.fn().mockResolvedValue(undefined),
    updatesCheck: vi.fn().mockResolvedValue({ state: "up-to-date" }),
    updatesApply: vi.fn().mockResolvedValue(undefined),
    keychainGetKekHandle: vi.fn().mockResolvedValue("opaque-handle-1"),
    notificationsShow: vi.fn().mockResolvedValue(undefined),
    crashLogAppend: vi.fn().mockResolvedValue(undefined),
    gpuInfo: vi.fn().mockResolvedValue({
      vendor: "NVIDIA",
      renderer: "NVIDIA GeForce",
      hardwareAccelerated: true,
      webgl2CapabilityParity: true,
    }),
    gpuRetry: vi.fn().mockResolvedValue(undefined),
    onGpuCrashed: vi.fn().mockReturnValue(() => {}),
    onDeepLink: vi.fn().mockReturnValue(() => {}),
  };
}

describe("createElectronShellAdapter", () => {
  afterEach(() => {
    delete (window as { cv?: CvBridge }).cv;
    vi.restoreAllMocks();
  });

  it("reports auto-update off until the release is signed (SR-115), with its reason; the rest on", () => {
    const adapter = createElectronShellAdapter();
    expect(adapter.capabilities).toEqual(ELECTRON_CAPABILITIES);
    const { reason, ...flags } = adapter.capabilities;
    expect(Object.keys(flags).filter((key) => !flags[key as keyof typeof flags])).toEqual([
      "autoUpdate",
    ]);
    expect(reason).toEqual({ autoUpdate: expect.stringMatching(/\S/) }); // hidden with a reason
  });

  it("forwards every method call to the matching named window.cv function, not a generic channel", async () => {
    const bridge = makeStubBridge();
    (window as { cv?: CvBridge }).cv = bridge;
    const adapter = createElectronShellAdapter();

    await adapter.windows.float("pane-1", "/dom");
    expect(bridge.windowsFloat).toHaveBeenCalledWith("pane-1", "/dom");

    await adapter.keychain.getKekHandle();
    expect(bridge.keychainGetKekHandle).toHaveBeenCalledTimes(1);

    await adapter.gpu.info();
    expect(bridge.gpuInfo).toHaveBeenCalledTimes(1);

    await adapter.windows.redock("win-1");
    expect(bridge.windowsRedock).toHaveBeenCalledWith("win-1");

    await adapter.windows.saveState([]);
    expect(bridge.windowsSaveState).toHaveBeenCalledWith([]);

    await adapter.windows.restoreState();
    expect(bridge.windowsRestoreState).toHaveBeenCalledTimes(1);

    await adapter.tray.setStatus("ok");
    expect(bridge.traySetStatus).toHaveBeenCalledWith("ok");

    await adapter.updates.check();
    expect(bridge.updatesCheck).toHaveBeenCalledTimes(1);

    await adapter.updates.apply();
    expect(bridge.updatesApply).toHaveBeenCalledTimes(1);

    await adapter.notifications.show("t", "b");
    expect(bridge.notificationsShow).toHaveBeenCalledWith("t", "b");

    await adapter.crashLog.append({ timestampMs: 1, message: "m" });
    expect(bridge.crashLogAppend).toHaveBeenCalledWith({ timestampMs: 1, message: "m" });

    const unsubscribe = adapter.deepLinks.onDeepLink(() => {});
    expect(bridge.onDeepLink).toHaveBeenCalledTimes(1);
    expect(typeof unsubscribe).toBe("function");

    await adapter.gpu.retry();
    expect(bridge.gpuRetry).toHaveBeenCalledTimes(1);

    const handleCrash = vi.fn();
    const stopCrashes = adapter.gpu.onCrashed(handleCrash);
    expect(bridge.onGpuCrashed).toHaveBeenCalledWith(handleCrash);
    expect(typeof stopCrashes).toBe("function");
  });

  it("throws a clear error if used before the preload script installed window.cv", () => {
    delete (window as { cv?: CvBridge }).cv;
    const adapter = createElectronShellAdapter();
    expect(() => adapter.windows.restoreState()).toThrow(/preload script did not run/i);
  });
});

describe("ShellPort <-> preload allow-list type sync", () => {
  beforeEach(() => {
    (window as { cv?: CvBridge }).cv = makeStubBridge();
  });

  afterEach(() => {
    delete (window as { cv?: CvBridge }).cv;
  });

  it("every ShellPort method has a corresponding named CvBridge function (compile-time checked)", () => {
    // This test exists to be a stable anchor: if a ShellPort method is added
    // without a matching CvBridge entry, ElectronShellAdapter.ts fails to
    // typecheck before this file ever runs. The runtime assertion below is a
    // secondary guard against a bridge object missing a key at runtime.
    const bridge = (window as { cv?: CvBridge }).cv;
    const expectedKeys: (keyof CvBridge)[] = [
      "windowsFloat",
      "windowsRedock",
      "windowsSaveState",
      "windowsRestoreState",
      "traySetStatus",
      "updatesCheck",
      "updatesApply",
      "keychainGetKekHandle",
      "notificationsShow",
      "crashLogAppend",
      "gpuInfo",
      "gpuRetry",
      "onGpuCrashed",
      "onDeepLink",
    ];
    for (const key of expectedKeys) {
      expect(bridge?.[key]).toBeInstanceOf(Function);
    }
  });
});
