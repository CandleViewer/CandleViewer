import type { Browser, BrowserContext, Page, Route } from "@playwright/test";
import { json, stubSession } from "./api";
import { installWsHarness, type WsHarness } from "./wsHarness";

// E09-Q02 (#293), stub level: one user's sessions as a server keeps them, shared by every browser context of
// a test. Each context is wired to its own session. Revoking a session (sign out everywhere, a revoke, the
// fifth wrong unlock) makes its next call a 401 and hangs up its socket as the hub does (`bye
// session_revoked`, then 4401: 23 4.3, 9.5). The clock is the store's own, never the wall clock: a test
// moves it with `advance`. Contract: `22-api-openapi.yaml` "Idle lock", `authUnlock`, `authLogout`.

/** The default idle lock (`session_service.py`: 5-60 min per user) and the absolute lifetime. */
export const IDLE_TIMEOUT_S = 900;
export const ABSOLUTE_LIFETIME_MS = 12 * 3_600_000;
/** `MAX_UNLOCK_ATTEMPTS`: the fifth consecutive wrong unlock password revokes the session. */
export const UNLOCK_STRIKES = 5;
/** What the stub's unlock accepts: a test value, not a credential. */
export const UNLOCK_PASSWORD = "e2e-unlock-pw";

export interface StubSession {
  readonly id: string;
  readonly device: string | null;
  readonly issuedMs: number;
  /** `last_seen_at`: sign-in, extend and unlock are the only activity (22 "Idle lock"). */
  lastSeenMs: number;
  revoked: boolean;
  strikes: number;
  /** Hangs up this session's socket as the hub does; set by `attach` when the page has a WS harness. */
  hangUp?: () => void;
}

/** A call the stub server saw, for asserting what the SPA sent. */
export interface Call {
  readonly session: string;
  readonly method: string;
  readonly path: string;
  readonly body: unknown;
}

/**
 * `sessions.py` `_unauthorized()`: the uniform 401 of a session route, also for a revoked or expired session. Only
 * `POST /auth/unlock` and `POST /auth/lock` answer `session_revoked`; every other route keeps this one, so none is
 * a session oracle (22 "Idle lock").
 */
const UNAUTHENTICATED = json(
  {
    type: "about:blank",
    title: "Unauthorized",
    status: 401,
    detail: "authentication required",
    code: "unauthenticated",
  },
  401,
);
/** `POST /auth/refresh`'s one 401, for every cause (22 `authRefresh`; `sessions.py` `_REFRESH_INVALID`). */
const REFRESH_INVALID = json(
  {
    type: "about:blank",
    title: "Unauthorized",
    status: 401,
    detail: "refresh_token_invalid",
    code: "refresh_token_invalid",
  },
  401,
);
/** `me.py` `_unauthenticated()`: `GET /me` has its own problem body. */
const ME_UNAUTHENTICATED = json(
  {
    type: "https://candleviewer.local/errors/unauthenticated",
    title: "Missing, malformed or expired access token",
    status: 401,
    code: "unauthenticated",
    detail: "Authentication is required.",
  },
  401,
);
const LOCKED = json({ status: 401, code: "session_idle_locked" }, 401);
const iso = (ms: number): string => new Date(ms).toISOString();
/** A request body as JSON when it is, else as the text it is: a beacon's body never makes the stub throw. */
function jsonOrText(raw: string | null): unknown {
  if (raw === null) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

export class SessionStore {
  /** The server's clock, epoch ms. */
  nowMs = Date.UTC(2026, 9, 30, 10, 0, 0);
  readonly sessions: StubSession[] = [];
  readonly calls: Call[] = [];

  mint(device: string | null = null): StubSession {
    const n = this.sessions.length + 2; // `00000000-0000-4000-8000-000000000002` is the first, as api.ts's rows
    const session = {
      id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
      device,
      issuedMs: this.nowMs,
      lastSeenMs: this.nowMs,
      revoked: false,
      strikes: 0,
    };
    this.sessions.push(session);
    return session;
  }

  /**
   * Moves the server's clock on, then the page's clock the same span, so the SPA's read finds the new time. The
   * page jumps (`fastForward`: each due timer fires once, as when a laptop wakes): ticking 15 simulated minutes
   * through `runFor` outruns the fake gateway's pongs and sets the shell's reconnect cycles spinning.
   */
  async advance(ms: number, page?: Page): Promise<void> {
    this.nowMs += ms;
    await page?.clock.fastForward(ms);
  }

  idleDeadlineMs = (s: StubSession): number => s.lastSeenMs + IDLE_TIMEOUT_S * 1000;
  isLocked = (s: StubSession): boolean => this.nowMs >= this.idleDeadlineMs(s);
  /** Revoked, or past the absolute lifetime. */
  isGone = (s: StubSession): boolean =>
    s.revoked || this.nowMs >= s.issuedMs + ABSOLUTE_LIFETIME_MS;

  revoke(s: StubSession): void {
    s.revoked = true;
    s.hangUp?.();
  }

  /** `SessionInfo` as `GET /auth/session`, extend and unlock answer it (the fields the SPA reads). */
  clock(s: StubSession): unknown {
    return {
      server_time: iso(this.nowMs),
      step_up_expires_at: null,
      session: {
        id: s.id,
        issued_at: iso(s.issuedMs),
        expires_at: iso(s.issuedMs + ABSOLUTE_LIFETIME_MS),
        idle_deadline: iso(this.idleDeadlineMs(s)),
        idle_timeout_s: IDLE_TIMEOUT_S,
        locked: this.isLocked(s),
      },
    };
  }

  /** `GET /auth/sessions` for `caller`: its own row first, then the user's other live sessions. */
  list(caller: StubSession): unknown {
    const live = this.sessions.filter((s) => !this.isGone(s));
    const items = [caller, ...live.filter((s) => s !== caller)].map((s) => ({
      id: s.id,
      device_name: s.device,
      ip: "100.64.0.7",
      user_agent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
      created_at: iso(s.issuedMs),
      last_seen_at: iso(s.lastSeenMs),
      expires_at: iso(s.issuedMs + ABSOLUTE_LIFETIME_MS),
      current: s === caller,
    }));
    return { items, meta: { next_cursor: null, has_more: false, count: items.length } };
  }

  /** The stub server for the calls of the idle lock and the sessions list; any other call falls through. */
  async serve(s: StubSession, route: Route): Promise<void> {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice("/api/v1".length);
    const method = request.method();
    const body = method === "POST" ? jsonOrText(request.postData()) : null;
    this.calls.push({ session: s.id, method, path, body });
    const other = /^\/me\/sessions\/([^/]+)$/u.exec(path)?.[1];
    const all = (body as { all_sessions?: boolean } | null)?.all_sessions === true;
    const gone = this.isGone(s);
    const locked = this.isLocked(s);
    const call = `${method} ${other === undefined ? path : "/me/sessions/{id}"}`;
    switch (call) {
      case "POST /auth/refresh":
        if (gone) return route.fulfill(REFRESH_INVALID);
        return locked ? route.fulfill(LOCKED) : route.fallback();
      case "GET /me":
        if (gone) return route.fulfill(ME_UNAUTHENTICATED);
        return locked ? route.fulfill(LOCKED) : route.fallback();
      case "GET /auth/session":
        return gone ? route.fulfill(UNAUTHENTICATED) : route.fulfill(json(this.clock(s)));
      case "POST /auth/session/extend":
        if (gone) return route.fulfill(UNAUTHENTICATED);
        if (locked) return route.fulfill(LOCKED);
        s.lastSeenMs = this.nowMs;
        return route.fulfill(json(this.clock(s)));
      case "POST /auth/unlock":
        return route.fulfill(this.unlock(s, body));
      case "POST /auth/logout":
        // 22 `authLogout`: everywhere is refused to a locked session; a plain logout ends only this one
        if (locked && all) return route.fulfill(LOCKED);
        for (const target of all ? this.sessions : [s]) this.revoke(target);
        return route.fulfill({ status: 204 });
      case "GET /auth/sessions":
        if (gone) return route.fulfill(UNAUTHENTICATED);
        return locked ? route.fulfill(LOCKED) : route.fulfill(json(this.list(s)));
      case "DELETE /me/sessions/{id}": {
        if (gone) return route.fulfill(UNAUTHENTICATED);
        const target = this.sessions.find((x) => x.id === other && !this.isGone(x));
        if (target === undefined)
          return route.fulfill(json({ status: 404, code: "not_found" }, 404));
        this.revoke(target);
        return route.fulfill({ status: 204 });
      }
      default:
        return route.fallback();
    }
  }

  private unlock(s: StubSession, body: unknown): ReturnType<typeof json> {
    const revoked = (reason?: string) =>
      json(
        { status: 401, code: "session_revoked", ...(reason && { revoked_reason: reason }) },
        401,
      );
    if (this.nowMs >= s.issuedMs + ABSOLUTE_LIFETIME_MS) return revoked("expired");
    if (s.revoked) return revoked();
    if (!this.isLocked(s)) return json({ status: 409, code: "conflict" }, 409);
    if ((body as { password?: string } | null)?.password === UNLOCK_PASSWORD) {
      s.strikes = 0;
      s.lastSeenMs = this.nowMs;
      return json(this.clock(s));
    }
    s.strikes += 1;
    if (s.strikes < UNLOCK_STRIKES) return json({ status: 401, code: "unlock_invalid" }, 401);
    this.revoke(s);
    return revoked("unlock_attempts_exceeded");
  }
}

/**
 * Wires `page` as `session`'s browser; call it before `goto`. With `ws`, a fake gateway answers its socket and
 * the stub server hangs it up when the session is revoked. A test that also fakes the page clock installs it from
 * the real time (`page.clock.install()`): the socket lives in a shared worker that `page.clock` does not reach,
 * and the worker judges the access token, stamped on the page's clock, by the real one.
 */
export async function attach(
  page: Page,
  store: SessionStore,
  session: StubSession,
  { ws = false } = {},
): Promise<WsHarness | undefined> {
  await stubSession(page, { role: "owner" });
  const harness = ws ? await installWsHarness(page) : undefined;
  if (harness !== undefined) {
    session.hangUp = () => {
      try {
        harness.revokeSession();
      } catch (error) {
        // the hub closes a session's live sockets: a client between two sockets has none to close
        if (!(error instanceof Error) || !error.message.endsWith("no live connection")) throw error;
      }
    };
  }
  // registered last, so it answers first and passes what it does not serve to the stubs above
  await page.route(
    (url) => url.pathname.startsWith("/api/v1/"),
    (route) => store.serve(session, route),
  );
  return harness;
}

export interface StubContext {
  readonly context: BrowserContext;
  readonly page: Page;
  readonly session: StubSession;
  readonly harness: WsHarness;
}

/** A new browser context (its own cookies, storage and shared worker) signed in as a new session of the store. */
export async function openContext(
  browser: Browser,
  store: SessionStore,
  device: string | null = null,
): Promise<StubContext> {
  const context = await browser.newContext();
  const page = await context.newPage();
  const session = store.mint(device);
  const harness = await attach(page, store, session, { ws: true });
  if (harness === undefined) throw new Error("openContext: no WS harness");
  return { context, page, session, harness };
}
