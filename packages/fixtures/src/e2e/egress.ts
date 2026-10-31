import type { BrowserContext } from "@playwright/test";

// E10-Q02 egress guard (C-13.5, C-13.7): no test reaches past the loopback interface. Checked by
// pattern, never by a host list: any http(s)/ws(s) request whose host is not loopback is aborted
// and recorded, and the test fails on any record.

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

/** True for a URL the suites may reach: loopback, or a scheme that never leaves the process. */
export function isLocal(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (!["http:", "https:", "ws:", "wss:"].includes(parsed.protocol)) return true; // app:, data:, blob:
  return LOOPBACK_HOSTS.has(parsed.hostname);
}

/** What a guard saw leave, as `<scheme>//<host>` only: no path or query reaches a report. */
const origin = (url: string): string => {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "<unparsable url>";
  }
};

export interface EgressGuard {
  /** Origins of the non-loopback requests and page sockets seen so far (each one was blocked). */
  readonly hits: () => readonly string[];
}

/**
 * Web half: a catch-all context route, below every page route a test installs (page routes run
 * first), so stubs still answer; anything else non-loopback is aborted. Page sockets the same way:
 * a context WebSocket route, again below any page harness, takes every non-loopback socket, never
 * connects it to a server, closes it and records it. A socket opened inside a shared or service
 * worker is outside Playwright's WebSocket routing and is not seen here.
 */
export async function guardContextEgress(context: BrowserContext): Promise<EgressGuard> {
  const hits: string[] = [];
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (isLocal(url)) return route.fallback();
    hits.push(origin(url));
    return route.abort("blockedbyclient");
  });
  await context.routeWebSocket(
    (url) => !isLocal(url.href),
    (ws) => {
      hits.push(origin(ws.url()));
      return ws.close({ code: 1008, reason: "egress blocked (C-13.5)" });
    },
  );
  return { hits: () => [...hits] };
}

/**
 * Electron half, run in the main process through `app.evaluate(ELECTRON_EGRESS_GUARD)`: the default
 * session's `onBeforeRequest` cancels and records every non-loopback request, sockets included
 * (`ws:`/`wss:` upgrades pass through `webRequest`), made in that session: any window on it and the
 * main process's own `net`/`session.fetch` calls, from the moment it is installed (after
 * `app.whenReady()`; startup requests before that are not seen). Only `defaultSession` is guarded:
 * the shell creates no other session or partition today, and one added later is not covered. `onBeforeRequest` replaces any
 * listener already on the session (the shell installs none today). Self-contained (serialised).
 */
export const ELECTRON_EGRESS_GUARD = (electron: unknown): void => {
  // Typed by hand: the package compiles without Electron's types, and the function is serialised.
  const { session } = electron as {
    session: {
      defaultSession: {
        webRequest: {
          onBeforeRequest: (
            listener: (d: { url: string }, cb: (r: { cancel: boolean }) => void) => void,
          ) => void;
        };
      };
    };
  };
  const loopback = /^(?:https?|wss?):\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?\//u;
  const remote = /^(?:https?|wss?):/u;
  const store = globalThis as unknown as { cvEgressHits?: string[] };
  store.cvEgressHits = [];
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    const blocked = remote.test(details.url) && !loopback.test(details.url);
    if (blocked) store.cvEgressHits?.push(details.url.replace(/^([a-z]+:\/\/[^/]+).*$/su, "$1"));
    callback({ cancel: blocked });
  });
};

/** Reads the Electron guard's record: `app.evaluate(ELECTRON_EGRESS_HITS)`. */
export const ELECTRON_EGRESS_HITS = (): string[] =>
  (globalThis as unknown as { cvEgressHits?: string[] }).cvEgressHits ?? [];
