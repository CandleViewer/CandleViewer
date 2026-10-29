import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BROWSER_CAPABILITIES,
  createBrowserShellAdapter,
} from "../../src/shell/BrowserShellAdapter.js";

describe("createBrowserShellAdapter", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reports every non-gpu capability as false with a human-readable reason", () => {
    const adapter = createBrowserShellAdapter();
    const caps = adapter.capabilities;

    expect(caps.floatingWindows).toBe(false);
    expect(caps.tray).toBe(false);
    expect(caps.autoUpdate).toBe(false);
    expect(caps.keychain).toBe(false);
    expect(caps.deepLinks).toBe(false);
    expect(caps.crashLog).toBe(false);

    for (const key of [
      "floatingWindows",
      "tray",
      "autoUpdate",
      "keychain",
      "deepLinks",
      "crashLog",
    ] as const) {
      expect(caps.reason[key]).toBeTruthy();
      expect(typeof caps.reason[key]).toBe("string");
    }
  });

  it("reports gpuInfo as available since a browser can probe WebGL2 honestly", () => {
    expect(BROWSER_CAPABILITIES.gpuInfo).toBe(true);
    expect(BROWSER_CAPABILITIES.reason.gpuInfo).toBeUndefined();
  });

  it("rejects windows.float with an explanatory error rather than pretending to succeed", async () => {
    const adapter = createBrowserShellAdapter();
    await expect(adapter.windows.float("pane-1", "/dom")).rejects.toThrow(/not available/i);
  });

  it("restoreState resolves to an empty list rather than throwing (nothing to restore)", async () => {
    const adapter = createBrowserShellAdapter();
    await expect(adapter.windows.restoreState()).resolves.toEqual([]);
  });

  it("updates.check resolves up-to-date without throwing (browser tabs update on reload)", async () => {
    const adapter = createBrowserShellAdapter();
    await expect(adapter.updates.check()).resolves.toEqual({ state: "up-to-date" });
  });

  it("deepLinks.onDeepLink returns a no-op unsubscribe rather than throwing", () => {
    const adapter = createBrowserShellAdapter();
    const unsubscribe = adapter.deepLinks.onDeepLink(() => {});
    expect(() => unsubscribe()).not.toThrow();
  });

  it("rejects windows.redock and windows.saveState with an explanatory error", async () => {
    const adapter = createBrowserShellAdapter();
    await expect(adapter.windows.redock("win-1")).rejects.toThrow(/not available/i);
    await expect(adapter.windows.saveState([])).rejects.toThrow(/not available/i);
  });

  it("rejects tray.setStatus, updates.apply, keychain.getKekHandle and crashLog.append", async () => {
    const adapter = createBrowserShellAdapter();
    await expect(adapter.tray.setStatus("ok")).rejects.toThrow(/not available/i);
    await expect(adapter.updates.apply()).rejects.toThrow(/not available/i);
    await expect(adapter.keychain.getKekHandle()).rejects.toThrow(/not available/i);
    await expect(adapter.crashLog.append({ timestampMs: 1, message: "m" })).rejects.toThrow(
      /not available/i,
    );
  });

  it("gpu.onCrashed is a no-op subscription and gpu.retry is refused (the crash state is Electron's)", async () => {
    const adapter = createBrowserShellAdapter();
    const handler = vi.fn();
    const unsubscribe = adapter.gpu.onCrashed(handler);
    expect(() => unsubscribe()).not.toThrow();
    expect(handler).not.toHaveBeenCalled();
    await expect(adapter.gpu.retry()).rejects.toThrow(/not available/i);
  });

  it("gpu.info returns a GpuInfo shape even without a real WebGL2 context", async () => {
    const adapter = createBrowserShellAdapter();
    const info = await adapter.gpu.info();
    expect(info).toHaveProperty("vendor");
    expect(info).toHaveProperty("renderer");
    expect(info).toHaveProperty("hardwareAccelerated");
    expect(info).toHaveProperty("webgl2CapabilityParity");
  });
});
