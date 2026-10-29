import { afterEach, describe, expect, it } from "vitest";
import { createShellPort } from "../../src/shell/index.js";
import type { CvBridge } from "../../src/shell/ElectronShellAdapter.js";

describe("createShellPort", () => {
  afterEach(() => {
    delete (window as { cv?: CvBridge }).cv;
  });

  it("selects the browser adapter when window.cv is absent", () => {
    const port = createShellPort();
    expect(port.capabilities.floatingWindows).toBe(false);
  });

  it("selects the electron adapter when window.cv is present (preload ran)", () => {
    (window as { cv?: CvBridge }).cv = {
      windowsFloat: async () => {},
      windowsRedock: async () => {},
      windowsSaveState: async () => {},
      windowsRestoreState: async () => [],
      traySetStatus: async () => {},
      updatesCheck: async () => ({ state: "up-to-date" }),
      updatesApply: async () => {},
      keychainGetKekHandle: async () => "h",
      notificationsShow: async () => {},
      crashLogAppend: async () => {},
      gpuInfo: async () => ({
        vendor: "v",
        renderer: "r",
        hardwareAccelerated: true,
        webgl2CapabilityParity: true,
      }),
      gpuRetry: async () => {},
      gpuKeepSoftware: async () => {},
      onGpuCrashed: () => () => {},
      onDeepLink: () => () => {},
    };
    const port = createShellPort();
    expect(port.capabilities.floatingWindows).toBe(true);
  });
});
