/**
 * Top-level shell start: runs the REST bootstrap and starts the web WS client concurrently (performance note: "the WS
 * connects concurrently rather than after them"). The client (E17-T04) is the tab's end of a port to a shared worker that
 * holds one engine and one socket for every tab: its `system` updates feed the shell store as they arrive, and its
 * connection state is mapped onto the shell's own. Exposed separately from `runBootstrap` so route guards can `await`
 * just the REST half without needing a live WS in tests.
 */
import { accessToken } from "../lib/auth/accessToken.js";
import { recordDecode } from "../lib/telemetry/aggregator.js";
import type { TokenSource } from "../lib/ws/api.js";
import { setActiveClient } from "../lib/ws/client/activeClient.js";
import { createWsClient } from "../lib/ws/client/createWsClient.js";
import { openWorkerPort } from "../lib/ws/client/workerPort.js";
import type { PortLike } from "../lib/ws/port/endpoint.js";
import type { WsState } from "../lib/ws/state/types.js";
import { runBootstrap, type BootstrapDeps } from "./bootstrap/bootstrap.js";
import { startLiveness } from "./bootstrap/liveness.js";
import { createBrowserShellAdapter } from "./BrowserShellAdapter.js";
import { installCrashReporter } from "./crash/reportCrash.js";
import {
  applySystemUpdate,
  clearDegraded,
  setShellState,
  type ConnectionState,
} from "./bootstrap/store.js";

/** The version `hello` names (`apps/web/package.json`, the build-time define the status bar shows). */
const CLIENT_VERSION = __CV_APP_VERSION__;

export interface StartShellOptions extends BootstrapDeps {
  readonly wsUrl: string;
  /** The WS client's token source: the tab's access-token holder (#2712) unless a test gives one. */
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
  // E10-S04: one crash reporter per shell, catching what no boundary does (window `error`, unhandled rejections)
  // The in-memory crash log for now: the Electron file log needs its IPC channel (a later slice), and importing the
  // Electron adapter here would pull its capabilities into the renderer bundle (SR-115's gate).
  const uninstallCrash = installCrashReporter({
    port: createBrowserShellAdapter(),
    version: CLIENT_VERSION,
  });
  // SCR-159 (#306 slice 9): the liveness probe's verdict, for the in-canvas offline states
  const liveness = startLiveness({ onChange: (reachability) => setShellState({ reachability }) });
  const teardown = (): void => {
    liveness.stop();
    uninstallCrash();
  };
  // ADR-0020: a page load re-derives the access token from the refresh cookie, once, before the bootstrap's first call.
  // `refresh` stops waiting after REFRESH_WAIT_MS (another tab may hold the lock), so the first paint does too.
  // #1640: a refresh answered `session_idle_locked` is a reload into a locked session. It mints no token, so the
  // bootstrap's `/me` would go cookie-only and answer `unauthenticated` (sign-in): SCR-005 comes first instead.
  const ready = accessToken
    .refresh()
    .then((outcome) =>
      outcome === "locked"
        ? setShellState({ bootstrap: { kind: "locked" } })
        : runBootstrap(options),
    );

  let port: PortLike;
  try {
    port = options.port ?? openWorkerPort();
  } catch (error) {
    // No worker can be started (a CSP that forbids one throws a `SecurityError`): the connection reads unreachable, and the REST
    // half still runs, so the app loads without a live feed instead of with a shell that never started.
    console.error("startShell: the worker's port could not be opened", error);
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    stopActive = teardown;
    return { ready, stop: teardown };
  }
  const opened = options.port === undefined;
  const client = createWsClient({
    wsUrl: options.wsUrl,
    tokens: options.tokens ?? accessToken,
    shell: typeof window !== "undefined" && window.cv ? "electron" : "browser",
    locale: (typeof navigator === "undefined" ? "" : navigator.language).slice(0, 16) || "en",
    clientVersion: CLIENT_VERSION,
    port,
    onSystem: (update) => applySystemUpdate(update),
    telemetry: { recordDecode }, // `fe_ws_decode_ms` (D8), into the app's aggregator
    onLatency: (latency) => setShellState({ latency }), // budget #3: the client throttles it to once a second
  });
  let wasLive = false;
  const forward = (): void => {
    const connection = toConnectionState(client.getState());
    const live = connection.kind === "live";
    if (wasLive && !live) liveness.probeNow(); // an observed loss: check now
    if (live && !wasLive) liveness.markReachable(); // an observed success: the server answered
    wasLive = live;
    setShellState({ connection });
  };
  client.subscribe(forward); // `client.stop()` drops it
  forward();
  setActiveClient(client);

  const stop = (): void => {
    client.stop();
    teardown();
    if (opened) port.close?.(); // what the shell opened it lets go of: a replaced shell leaves one worker, not two
    if (stopActive === stop) {
      stopActive = null;
      setActiveClient(null);
      clearDegraded(); // the facts and row 9's timer are this client's; nothing fires after stop()
    }
  };
  stopActive = stop;
  return { ready, stop };
}
