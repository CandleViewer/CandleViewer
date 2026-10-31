import type { Page } from "@playwright/test";
import { pageBridge, workerShim } from "../wsHarness";

// E09-Q02 (#293) PR 3 (#2086): a passthrough tap on the real lane's socket (BQ-4). The SPA's socket
// lives in a shared worker, which `page.routeWebSocket` cannot see, so the stub harness's
// `pageBridge` and `workerShim` move it into the page, and the route connects it to the real
// gateway through the preview's proxy. The tap only records what the server sent and how it
// closed: it never answers, holds or changes a frame, and it keeps no client frame (the client's
// `auth` carries the access token). One page per context: every page of a context with the bridge
// would open the worker's socket.

/** The bridge's BroadcastChannel: not the stub harness's, which the production check looks for. */
const TAP_CHANNEL = "cv-e2e-ws-tap";

/** A server close as the page's socket saw it. */
export interface TapClose {
  readonly code: number | undefined;
  readonly reason: string | undefined;
}

export interface WsTap {
  /** The server's JSON frames, in order, across the page's sockets. */
  readonly frames: readonly Readonly<Record<string, unknown>>[];
  /** The server's closes, in order. */
  readonly closes: readonly TapClose[];
  /** The sockets the page opened. */
  connections(): number;
}

/** Taps `page`'s sockets to `/api/v1/ws`; call it before the page loads the SPA. */
export async function tapWebSocket(page: Page): Promise<WsTap> {
  const frames: Record<string, unknown>[] = [];
  const closes: TapClose[] = [];
  let opened = 0;
  await page.routeWebSocket("**/api/v1/ws", (ws) => {
    opened += 1;
    const server = ws.connectToServer();
    // A handler stops Playwright's own forwarding of that direction, so each one forwards.
    server.onMessage((message) => {
      if (typeof message === "string") {
        try {
          frames.push(JSON.parse(message) as Record<string, unknown>);
        } catch {
          // not JSON: forwarded all the same
        }
      }
      ws.send(message);
    });
    server.onClose((code, reason) => {
      closes.push({ code, reason });
      // The page may be gone already (its context closing): then there is nothing left to close.
      ws.close(code === undefined ? {} : { code, reason: reason ?? "" }).catch(() => undefined);
    });
  });
  await page.addInitScript(pageBridge, {
    name: TAP_CHANNEL,
    shim: `(${workerShim.toString()})(${JSON.stringify(TAP_CHANNEL)});`,
  });
  return { frames, closes, connections: () => opened };
}
