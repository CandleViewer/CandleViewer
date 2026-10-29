import type {
  CrashEntry,
  DeepLinkPayload,
  GpuCrash,
  GpuInfo,
  ShellCapabilities,
  ShellPort,
  TrayStatus,
  UpdateStatus,
  WindowState,
} from "./ShellPort.js";

/**
 * Typed shape of `window.cv`, the single bridge object exposed by
 * `apps/desktop`'s preload script via `contextBridge.exposeInMainWorld`
 * (SR-111: fixed, typed, allowlisted — no generic `invoke(channel, ...)`).
 * This file imports nothing from `electron` or `apps/desktop`; it only
 * describes the global the preload script promises to install, which keeps
 * `apps/web` free of any Electron/desktop dependency
 * (`.dependency-cruiser.js` `web-not-to-desktop`).
 */
export interface CvBridge {
  readonly windowsFloat: (paneId: string, route: string) => Promise<void>;
  readonly windowsRedock: (windowId: string) => Promise<void>;
  readonly windowsSaveState: (state: readonly WindowState[]) => Promise<void>;
  readonly windowsRestoreState: () => Promise<readonly WindowState[]>;
  readonly traySetStatus: (status: TrayStatus) => Promise<void>;
  readonly updatesCheck: () => Promise<UpdateStatus>;
  readonly updatesApply: () => Promise<void>;
  readonly keychainGetKekHandle: () => Promise<string>;
  readonly notificationsShow: (title: string, body: string) => Promise<void>;
  readonly crashLogAppend: (entry: CrashEntry) => Promise<void>;
  readonly gpuInfo: () => Promise<GpuInfo>;
  readonly gpuRetry: () => Promise<void>;
  readonly onGpuCrashed: (handler: (crash: GpuCrash) => void) => () => void;
  readonly onDeepLink: (handler: (payload: DeepLinkPayload) => void) => () => void;
}

declare global {
  interface Window {
    cv?: CvBridge;
  }
}

/**
 * Auto-update is off until the release is signed (E10-T02, SR-115): main's
 * `isAutoUpdateEnabled()` is a constant `false`, and the hardening gate fails
 * any renderer bundle that says otherwise. Its reason is E10-D03 §9.1's
 * pre-signing sentence (Q11, the owner's PROPOSED copy).
 */
export const ELECTRON_CAPABILITIES: ShellCapabilities = Object.freeze({
  floatingWindows: true,
  tray: true,
  autoUpdate: false,
  keychain: true,
  osNotifications: true,
  gpuInfo: true,
  deepLinks: true,
  crashLog: true,
  reason: Object.freeze({
    autoUpdate: "Updates are installed from the release page until signed auto-updates ship.",
  }),
});

function requireBridge(): CvBridge {
  if (!window.cv) {
    throw new Error(
      "ElectronShellAdapter used but window.cv is not present — preload script did not run.",
    );
  }
  return window.cv;
}

/**
 * `gpu.onCrashed`: each `cv:gpu:crashed`, and the last crash before the subscription (main pushed
 * it to no listener: at boot, or during a reload), read once from `cv:gpu:info` (#4951). One a
 * retry answered is the relaunch's, and an answer after the unsubscribe is dropped. A crash that
 * both bring reaches `handler` twice; the GPU watcher takes it once.
 */
function onGpuCrashed(bridge: CvBridge, handler: (crash: GpuCrash) => void): () => void {
  const unsubscribe = bridge.onGpuCrashed(handler);
  let subscribed = true;
  const replay = async (): Promise<void> => {
    const { lastCrash } = await bridge.gpuInfo();
    if (subscribed && lastCrash?.retried === false) handler(lastCrash);
  };
  // a failed read (a refused answer, say) shows no page: one fixed line, never its error (C-12.6)
  void replay().catch(() => console.error("gpu.onCrashed: the last-crash read failed"));
  return () => {
    subscribed = false;
    unsubscribe();
  };
}

/**
 * Preload-backed adapter. Every method here forwards to a named function on
 * `window.cv`; there is no method that accepts a caller-supplied channel
 * name, satisfying SR-111 end to end (the allow-list on the main-process
 * side is `apps/desktop/src/preload/allowList.ts`).
 */
export function createElectronShellAdapter(): ShellPort {
  return {
    capabilities: ELECTRON_CAPABILITIES,
    windows: {
      float: (paneId, route) => requireBridge().windowsFloat(paneId, route),
      redock: (windowId) => requireBridge().windowsRedock(windowId),
      saveState: (state) => requireBridge().windowsSaveState(state),
      restoreState: () => requireBridge().windowsRestoreState(),
    },
    tray: {
      setStatus: (status) => requireBridge().traySetStatus(status),
    },
    updates: {
      check: () => requireBridge().updatesCheck(),
      apply: () => requireBridge().updatesApply(),
    },
    keychain: {
      getKekHandle: () => requireBridge().keychainGetKekHandle(),
    },
    deepLinks: {
      onDeepLink: (handler) => requireBridge().onDeepLink(handler),
    },
    notifications: {
      show: (title, body) => requireBridge().notificationsShow(title, body),
    },
    crashLog: {
      append: (entry) => requireBridge().crashLogAppend(entry),
    },
    gpu: {
      info: () => requireBridge().gpuInfo(),
      onCrashed: (handler) => onGpuCrashed(requireBridge(), handler),
      retry: () => requireBridge().gpuRetry(),
    },
  };
}
