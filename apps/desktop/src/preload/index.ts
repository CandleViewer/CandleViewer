import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import { ALLOWED_IPC_CHANNELS, ALLOWED_IPC_EVENTS, isChannelAllowed } from "./allowList.js";
import { parseCrashEntry } from "../main/crashEntry.js";
import { parseGpuCrash, parseGpuLastCrash, type GpuCrash } from "../main/gpuCrash.js";

/**
 * Exposes exactly one namespaced object, `window.cv`, as a fixed set of
 * named, typed functions (SR-111). There is no generic
 * `invoke(channel, ...)` and no `ipcRenderer` passthrough exposed to the
 * renderer: each function below but `onGpuCrashed` (which subscribes through
 * `subscribeAllowed`) calls `ipcRenderer.invoke` with a literal,
 * compile-time-constant channel string, never a caller-supplied one, and
 * `invokeAllowed` re-asserts the channel is on `ALLOWED_IPC_CHANNELS` before
 * every call as defence-in-depth against a future refactor accidentally
 * making the channel dynamic.
 */
function invokeAllowed(channel: string, ...args: unknown[]): Promise<unknown> {
  if (!isChannelAllowed(channel, ALLOWED_IPC_CHANNELS)) {
    throw new Error(`IPC channel "${channel}" is not on the allow-list`);
  }
  return ipcRenderer.invoke(channel, ...args);
}

/**
 * The one way to listen to main: re-asserts the channel is on ALLOWED_IPC_EVENTS, hands `listener`
 * the payload alone, never the IPC event (whose `sender` is ipcRenderer itself), and returns the
 * unsubscribe.
 */
function subscribeAllowed(channel: string, listener: (payload: unknown) => void): () => void {
  if (!isChannelAllowed(channel, ALLOWED_IPC_EVENTS)) {
    throw new Error(`IPC event "${channel}" is not on the allow-list`);
  }
  const forward = (_event: IpcRendererEvent, payload: unknown): void => listener(payload);
  ipcRenderer.on(channel, forward);
  return () => {
    ipcRenderer.removeListener(channel, forward);
  };
}

/**
 * Main's `cv:gpu:info` answer with its `lastCrash` (#4951) checked as `cv:gpu:crashed`'s payload
 * is: a fresh copy or null. An answer that fails the check is refused.
 */
function checkedGpuInfo(info: unknown): object {
  if (typeof info === "object" && info !== null && !Array.isArray(info)) {
    const lastCrash = parseGpuLastCrash((info as { lastCrash?: unknown }).lastCrash);
    if (lastCrash !== undefined) {
      return { ...info, lastCrash };
    }
  }
  throw new Error("GPU info refused");
}

const cv = Object.freeze({
  gpuInfo: () => invokeAllowed("cv:gpu:info").then(checkedGpuInfo),
  keychainGetKekHandle: () => invokeAllowed("cv:keychain:getKekHandle"),
  updatesCheck: () => invokeAllowed("cv:updates:check"),
  // Only a fresh, schema-checked copy crosses to main; main checks it again (SR-111).
  crashLogAppend: (entry: unknown) => {
    const checked = parseCrashEntry(entry);
    if (checked === undefined) {
      return Promise.reject(new Error("Crash log entry refused"));
    }
    return invokeAllowed("cv:crashLog:append", checked);
  },
  // No caller argument crosses; main relaunches only after a GPU crash, and rate-limits it.
  gpuRetry: () => invokeAllowed("cv:gpu:retry"),
  // No caller argument crosses; main keeps this launch's last GPU crash, refused before one.
  gpuKeepSoftware: () => invokeAllowed("cv:gpu:keepSoftware"),
  // Each GPU-process crash (F15), as a fresh copy checked here again.
  onGpuCrashed: (listener: (crash: GpuCrash) => void) => {
    if (typeof listener !== "function") {
      throw new TypeError("GPU crash listener must be a function");
    }
    return subscribeAllowed("cv:gpu:crashed", (payload) => {
      const crash = parseGpuCrash(payload);
      if (crash !== undefined) {
        listener(crash);
      }
    });
  },
});

contextBridge.exposeInMainWorld("cv", cv);
