import type { ShellPort } from "./ShellPort.js";
import { createBrowserShellAdapter } from "./BrowserShellAdapter.js";
import { createElectronShellAdapter } from "./ElectronShellAdapter.js";

/**
 * Picks the adapter matching the current host: `window.cv` present means the
 * Electron preload script ran, so use the preload-backed adapter; otherwise
 * fall back to the honest-degradation browser adapter. Never sniffs the user
 * agent — the presence of the typed bridge is the only signal. A module of its
 * own, so the GPU watcher (bootstrap/gpuCrash.ts) reads through it without importing the index.
 */
export function createShellPort(): ShellPort {
  return typeof window !== "undefined" && window.cv
    ? createElectronShellAdapter()
    : createBrowserShellAdapter();
}
