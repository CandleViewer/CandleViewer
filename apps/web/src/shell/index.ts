export type {
  CrashEntry,
  DeepLinkPayload,
  GpuInfo,
  ShellCapabilities,
  ShellPort,
  TrayStatus,
  UpdateStatus,
  WindowBounds,
  WindowState,
} from "./ShellPort.js";
export { BROWSER_CAPABILITIES, createBrowserShellAdapter } from "./BrowserShellAdapter.js";
export {
  ELECTRON_CAPABILITIES,
  createElectronShellAdapter,
  type CvBridge,
} from "./ElectronShellAdapter.js";

export { useShellState } from "./useShellState.js";
export { useShellSelector } from "./useShellSelector.js";
export { startShell, type StartShellOptions } from "./startShell.js";
export {
  getShellState,
  subscribeShellState,
  resetShellState,
  INITIAL_SHELL_STATE,
  type ShellState,
  type BootstrapPhase,
  type ConnectionState,
  type Environment,
  type Me,
  type Settings,
  type Keymap,
  type SystemUpdate,
} from "./bootstrap/store.js";
export {
  runBootstrap,
  BOOTSTRAP_TIMEOUT_MS,
  SLOW_BOOT_THRESHOLD_MS,
} from "./bootstrap/bootstrap.js";
export {
  orderSubscriptionsForRestore,
  type SubscriptionRequest,
  type SubscriptionPriority,
} from "./bootstrap/subscriptionOrder.js";

import type { ShellPort } from "./ShellPort.js";
import { createBrowserShellAdapter } from "./BrowserShellAdapter.js";
import { createElectronShellAdapter } from "./ElectronShellAdapter.js";

/**
 * Picks the adapter matching the current host: `window.cv` present means the
 * Electron preload script ran, so use the preload-backed adapter; otherwise
 * fall back to the honest-degradation browser adapter. Never sniffs the user
 * agent — the presence of the typed bridge is the only signal.
 */
export function createShellPort(): ShellPort {
  return typeof window !== "undefined" && window.cv
    ? createElectronShellAdapter()
    : createBrowserShellAdapter();
}
