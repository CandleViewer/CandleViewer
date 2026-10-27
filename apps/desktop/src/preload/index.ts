import { contextBridge, ipcRenderer } from "electron";
import { ALLOWED_IPC_CHANNELS, isChannelAllowed } from "./allowList.js";
import { parseCrashEntry } from "../main/crashEntry.js";

/**
 * Exposes exactly one namespaced object, `window.cv`, as a fixed set of
 * named, typed functions (SR-111). There is no generic
 * `invoke(channel, ...)` and no `ipcRenderer` passthrough exposed to the
 * renderer: each function below calls `ipcRenderer.invoke` with a literal,
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

const cv = Object.freeze({
  gpuInfo: () => invokeAllowed("cv:gpu:info"),
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
});

contextBridge.exposeInMainWorld("cv", cv);
