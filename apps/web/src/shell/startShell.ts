/**
 * Top-level shell start: runs the REST bootstrap and starts the web WS client concurrently (performance note: "the WS
 * connects concurrently rather than after them"). The client (E17-T04) is the tab's end of a port to a shared worker that
 * holds one engine and one socket for every tab: its `system` updates feed the shell store as they arrive, and its
 * connection state is mapped onto the shell's own. Exposed separately from `runBootstrap` so route guards can `await`
 * just the REST half without needing a live WS in tests.
 */
import type { TokenSource } from "../lib/ws/api.js";
import { setActiveClient } from "../lib/ws/client/activeClient.js";
import { createWsClient } from "../lib/ws/client/createWsClient.js";
import { openWorkerPort } from "../lib/ws/client/workerPort.js";
import type { PortLike } from "../lib/ws/port/endpoint.js";
import type { WsState } from "../lib/ws/state/types.js";
import { runBootstrap, type BootstrapDeps } from "./bootstrap/bootstrap.js";
import { applySystemUpdate, setShellState, type ConnectionState } from "./bootstrap/store.js";

/** The version `hello` names (`apps/web/package.json`); nothing injects it at build time yet. */
const CLIENT_VERSION = "0.1.0";

/**
 * #2712 holds the access token in memory and refreshes it; until it lands there is none to give. The connection then reads
 * offline and asks again on the backoff table (23 9.2), never in a loop.
 */
export const unavailableTokens: TokenSource = {
  getToken: () => Promise.resolve({ kind: "unavailable" }),
  invalidate: () => undefined,
};

export interface StartShellOptions extends BootstrapDeps {
  readonly wsUrl: string;
  readonly tokens?: TokenSource | undefined;
  /** The tab's end of the port to the worker: the shared worker the browser gives (a dedicated one without), or a test's fake. */
  readonly port?: PortLike | undefined;
}

/** `fatal` (a close that forbids a reconnect: 1002, 1009, 4400, 4403) is the shell's backend that cannot be reached. */
export function toConnectionState(state: WsState): ConnectionState {
  const { link } = state;
  switch (link.kind) {
    case "connecting":
      return { kind: "connecting" };
    case "up":
      return { kind: "live" };
    case "reconnecting":
      return { kind: "reconnecting", attempt: link.attempt, nextAttemptAtMs: link.nextAttemptAtMs };
    case "offline":
      return {
        kind: "offline",
        cause: link.cause === "fatal" ? "backend_unreachable" : link.cause,
      };
  }
}

let stopActive: (() => void) | null = null;

/** Starts the bootstrap fetch and the WS client. Returns a `stop()` to tear down the client (used by tests and by logout). */
export function startShell(options: StartShellOptions): { stop(): void; ready: Promise<void> } {
  stopActive?.();

  let port: PortLike;
  try {
    port = options.port ?? openWorkerPort();
  } catch (error) {
    // No worker can be started (a CSP that forbids one throws a `SecurityError`): the connection reads unreachable, and the REST
    // half still runs, so the app loads without a live feed instead of with a shell that never started.
    console.error("startShell: the worker's port could not be opened", error);
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    return { ready: runBootstrap(options), stop: () => undefined };
  }
  const client = createWsClient({
    wsUrl: options.wsUrl,
    tokens: options.tokens ?? unavailableTokens,
    shell: typeof window !== "undefined" && window.cv ? "electron" : "browser",
    locale: (typeof navigator === "undefined" ? "" : navigator.language).slice(0, 16) || "en",
    clientVersion: CLIENT_VERSION,
    port,
    onSystem: (update) => applySystemUpdate(update),
  });
  const forward = (): void => setShellState({ connection: toConnectionState(client.getState()) });
  client.subscribe(forward); // `client.stop()` drops it
  forward();
  setActiveClient(client);

  const ready = runBootstrap(options);

  const stop = (): void => {
    client.stop();
    if (stopActive === stop) {
      stopActive = null;
      setActiveClient(null);
    }
  };
  stopActive = stop;
  return { ready, stop };
}
