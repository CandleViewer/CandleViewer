import type { GpuInfo, ShellCapabilities, ShellPort, UpdateStatus } from "./ShellPort.js";

/**
 * No-op `ShellPort` for a plain browser tab. Every capability the browser
 * genuinely cannot provide reports `false` with a human-readable reason
 * string (US-SET-009: "hidden with an explanation", never shown disabled).
 * `gpuInfo` is the one capability a browser *can* honestly provide (via
 * `WEBGL_debug_renderer_info`), so it stays available here.
 */
const REASON = {
  floatingWindows: "Multi-window workspaces need the desktop app.",
  tray: "A system tray is not available in a browser tab.",
  autoUpdate: "Browser tabs update on page reload; there is no installer to update.",
  keychain: "The OS keychain bridge is only available in the desktop app.",
  osNotifications:
    "Enable browser notification permission, or use the desktop app for OS-level alerts.",
  deepLinks: "Deep links (custom protocol) require the desktop app.",
  crashLog: "Crash logs are written to the desktop app's local log file only.",
} as const;

export const BROWSER_CAPABILITIES: ShellCapabilities = Object.freeze({
  floatingWindows: false,
  tray: false,
  autoUpdate: false,
  keychain: false,
  osNotifications: typeof Notification !== "undefined" && Notification.permission === "granted",
  gpuInfo: true,
  deepLinks: false,
  crashLog: false,
  reason: Object.freeze({
    floatingWindows: REASON.floatingWindows,
    tray: REASON.tray,
    autoUpdate: REASON.autoUpdate,
    keychain: REASON.keychain,
    ...(typeof Notification === "undefined" || Notification.permission !== "granted"
      ? { osNotifications: REASON.osNotifications }
      : {}),
    deepLinks: REASON.deepLinks,
    crashLog: REASON.crashLog,
  }),
});

async function probeGpuInfo(): Promise<GpuInfo> {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl2");
  if (!gl) {
    return {
      vendor: "unknown",
      renderer: "unknown",
      hardwareAccelerated: false,
      webgl2CapabilityParity: false,
    };
  }
  const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
  const vendor = debugInfo ? String(gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)) : "unknown";
  const renderer = debugInfo
    ? String(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL))
    : "unknown";
  const webgl2CapabilityParity = Boolean(
    gl.getExtension("EXT_color_buffer_float") && gl.getExtension("OES_texture_float_linear"),
  );
  return {
    vendor,
    renderer,
    hardwareAccelerated: !/swiftshader|software/i.test(renderer),
    webgl2CapabilityParity,
  };
}

function unavailable(name: string): never {
  throw new Error(`ShellPort capability "${name}" is not available in a browser tab.`);
}

/** Capability-false, no-op adapter. See module doc for the degradation policy. */
export function createBrowserShellAdapter(): ShellPort {
  return {
    capabilities: BROWSER_CAPABILITIES,
    windows: {
      float: async () => unavailable("windows.float"),
      redock: async () => unavailable("windows.redock"),
      saveState: async () => unavailable("windows.saveState"),
      restoreState: async () => [],
    },
    tray: {
      setStatus: async () => unavailable("tray.setStatus"),
    },
    updates: {
      check: async (): Promise<UpdateStatus> => ({ state: "up-to-date" }),
      apply: async () => unavailable("updates.apply"),
    },
    keychain: {
      getKekHandle: async () => unavailable("keychain.getKekHandle"),
    },
    deepLinks: {
      onDeepLink: () => () => {},
    },
    notifications: {
      show: async (title: string, body: string) => {
        if (!BROWSER_CAPABILITIES.osNotifications) {
          unavailable("notifications.show");
        }
        new Notification(title, { body });
      },
    },
    crashLog: {
      append: async () => unavailable("crashLog.append"),
    },
    gpu: {
      info: probeGpuInfo,
      // The crash state is the desktop shell's (F15); a tab keeps SCR-153's banner.
      onCrashed: () => () => {},
      retry: async () => unavailable("gpu.retry"),
    },
  };
}
