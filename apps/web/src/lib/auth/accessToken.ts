/**
 * #2712: the access token (ADR-0020 decisions 1, 3 and 5; `23-ws-protocol.md` §4.3).
 *
 * - Held in memory only: never in storage, a cookie, a URL, a log or an error message.
 * - One token per origin. The server keeps one live access token per session: a refresh or a step-up
 *   revokes the one before as `rotated`. So a bundle a tab receives is posted to its same-origin siblings
 *   over the `cv.auth.token` BroadcastChannel (memory to memory, never storage), and each holds it in
 *   place of the token that rotation revoked.
 * - `send` gives it as `Authorization: Bearer` to same-origin `/api/v1/` URLs and to nothing else.
 * - It is refreshed at `expires_at - 60 s` through `POST /auth/refresh` (the `cv_refresh` cookie and the
 *   CSRF header): one refresh at a time in the tab, and across tabs under the `cv.auth.refresh` Web Lock,
 *   because the refresh cookie is single-use and presenting a spent one revokes the session family. For
 *   the same reason a refresh once sent is never aborted: a caller stops waiting after `REFRESH_WAIT_MS`,
 *   the refresh goes on, and the bundle it gets is held.
 * - The WS client reads it through `getToken`: `ok`, `locked` (`401 session_idle_locked`; nothing is
 *   cleared) or `unavailable`. Any other `401` from the refresh, or `endSession`, forgets it and routes to
 *   sign-in (SCR-001); a logout's `2xx` forgets it.
 */
import type { ErrorCode, generated } from "@candleviewer/protocol";
import { CSRF_HEADER, readCsrfCookie } from "../http/csrfCookie";
import { sameOriginUrl } from "../http/sameOrigin";
import type { TokenResult, TokenSource } from "../ws/api";

export type TokenBundle = generated.rest.components["schemas"]["TokenBundle"];
export type RefreshOutcome = "ok" | "locked" | "lost" | "failed";
type Transport = (init: RequestInit) => Promise<Response>;

export const REFRESH_PATH = "/api/v1/auth/refresh";
export const REFRESH_LOCK = "cv.auth.refresh";
/** The same-origin channel a tab posts the bundles it receives on. */
export const TOKEN_CHANNEL = "cv.auth.token";
export const SIGN_IN_PATH = "/login";
/** 23 §4.3: the token is renewed at `expires_at - 60 s`. */
export const REFRESH_LEAD_MS = 60_000;
/**
 * `getToken` hands out no token inside its last `REFRESH_LEAD_MS` and this much more: the WS client
 * re-auths 60 s before the server's expiry, which is earlier than this tab's (receipt time) by the latency.
 */
const HANDOUT_SLACK_MS = 5_000;
/** How long a caller waits for a refresh: the shell's first paint waits for the page-load one. */
export const REFRESH_WAIT_MS = 10_000;
/** How long a refresh that finds the session rotated by a sibling waits for that sibling's bundle. */
const SIBLING_WAIT_MS = 1_000;
const SESSION_PATH = "/api/v1/auth/session";
const LOGOUT_PATH = "/api/v1/auth/logout";
const API_PREFIX = "/api/v1/";
const AUTH_PREFIX = "/api/v1/auth/";
const IDLE_LOCKED: ErrorCode = "session_idle_locked";
const CSRF_REFUSED: ErrorCode = "csrf_token_invalid";
/** A short-lived token never makes a hot loop, and a timer past 2^31 ms would fire at once. */
const MIN_DELAY_MS = 5_000;
const MAX_DELAY_MS = 2 ** 31 - 1;
/** The calls that mint or rotate a session and answer a `TokenBundle` (`22-api-openapi.yaml`). */
const MINTING: ReadonlySet<string> = new Set([
  "/api/v1/auth/login",
  "/api/v1/auth/mfa/verify",
  "/api/v1/auth/mfa/recovery",
  "/api/v1/auth/mfa/enroll/confirm",
  "/api/v1/auth/step-up",
]);
/** The pre-session ones (`security: []`): no bearer goes to them. */
const PRE_SESSION: ReadonlySet<string> = new Set([
  "/api/v1/auth/login",
  "/api/v1/auth/mfa/verify",
  "/api/v1/auth/mfa/recovery",
]);
/**
 * The auth calls whose refusal judges no password or code, so a renewed token may repeat them. Any
 * other auth call is never repeated: its 401 may judge a credential, and a repeat counts a second failure.
 */
const AUTH_REPEATABLE: ReadonlySet<string> = new Set([
  "/api/v1/auth/session",
  "/api/v1/auth/session/extend",
  "/api/v1/auth/session/view-as",
  "/api/v1/auth/sessions",
  "/api/v1/auth/logout",
  "/api/v1/auth/mfa/enroll",
]);
/** RFC 6750 `b64token`: what `Headers` takes as it is, so the value never ends up in a `TypeError`. */
const B64TOKEN = /^[A-Za-z0-9\-._~+/]+=*$/;

export interface AccessTokenHolder extends TokenSource {
  /**
   * Holds a bundle from sign-in, MFA, step-up or refresh (it expires `expires_in` s after receipt), and
   * posts it to the sibling tabs.
   */
  set(bundle: TokenBundle): void;
  /** Forgets the token: `getToken` answers `unavailable` until the next bundle; a refresh on the wire is dropped. */
  clear(): void;
  /** Logout or a lost session: forgets the token and routes to sign-in. */
  endSession(): void;
  /** One refresh, shared by every caller while it runs; never rejects; `failed` once `REFRESH_WAIT_MS` pass. */
  refresh(): Promise<RefreshOutcome>;
  /**
   * Sends with the bearer to a same-origin API URL. A refusal a new token cures (a 401, or a CSRF refusal
   * of the bearer sent) renews it and repeats the call once; a returned bundle is held.
   */
  send(input: RequestInfo | URL, init: RequestInit, transport: Transport): Promise<Response>;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

function isBundle(value: unknown): value is TokenBundle {
  if (!isRecord(value)) return false;
  const { access_token: token, expires_in: expiresIn, token_type: type } = value;
  return (
    typeof token === "string" &&
    B64TOKEN.test(token) &&
    type === "Bearer" &&
    typeof expiresIn === "number" &&
    Number.isFinite(expiresIn) &&
    expiresIn > 0
  );
}

const tokensOf = (body: unknown): unknown => (isRecord(body) ? body["tokens"] : undefined);

/** The problem `code` of a response, if its body is JSON that has one. */
async function codeOf(res: Response): Promise<unknown> {
  try {
    const body: unknown = await res.clone().json();
    return isRecord(body) ? body["code"] : undefined;
  } catch {
    return undefined; // no JSON body
  }
}

/** The path of a same-origin `/api/v1/` URL, else `null`: another origin, or no URL, gets no bearer. */
function apiPath(input: RequestInfo | URL): string | null {
  const url = sameOriginUrl(input);
  return url !== null && url.pathname.startsWith(API_PREFIX) ? url.pathname : null;
}

function withBearer(input: RequestInfo | URL, init: RequestInit, token: string): RequestInit {
  // `init.headers` replaces a Request's own, so those are carried over
  const headers = new Headers(
    init.headers ?? (input instanceof Request ? input.headers : undefined),
  );
  headers.set("Authorization", `Bearer ${token}`);
  // a redirect to another origin is a network error, whatever a browser does with the header on one
  return { ...init, headers, mode: "same-origin" };
}

/** Runs `task` under the cross-tab lock; a browser without Web Locks has the in-tab single flight only. */
async function exclusive<T>(task: () => Promise<T>): Promise<T> {
  const locks: LockManager | undefined = navigator.locks;
  return locks === undefined ? task() : locks.request(REFRESH_LOCK, task);
}

/** `outcome`, or `failed` once `REFRESH_WAIT_MS` pass or `signal` aborts: the caller stops, the refresh goes on. */
function waitFor(
  outcome: Promise<RefreshOutcome>,
  signal?: AbortSignal | null,
): Promise<RefreshOutcome> {
  return new Promise((resolve) => {
    const settle = (value: RefreshOutcome): void => {
      clearTimeout(timeout);
      signal?.removeEventListener("abort", stop);
      resolve(value);
    };
    const stop = (): void => settle("failed");
    const timeout = setTimeout(stop, REFRESH_WAIT_MS);
    signal?.addEventListener("abort", stop);
    if (signal?.aborted === true) stop();
    void outcome.then(settle);
  });
}

/** A same-origin channel to the sibling tabs, where the browser has one. */
function openChannel(): BroadcastChannel | null {
  const Channel: typeof BroadcastChannel | undefined = globalThis.BroadcastChannel;
  return Channel === undefined ? null : new Channel(TOKEN_CHANNEL);
}

export function createAccessTokenHolder(toSignIn: () => void): AccessTokenHolder {
  let token: { readonly value: string; readonly expiresAtMs: number } | null = null;
  /** The WS client or a refused call reported it rejected: the next ask refreshes. */
  let stale = false;
  /** A refresh found no session, or it ended: `unavailable` without asking again, until a bundle. */
  let signedOut = false;
  /** Counts the sessions this tab ended: a refresh that answers after one is not held. */
  let ended = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight: Promise<RefreshOutcome> | null = null;
  /** Refreshes that wait for a sibling's bundle. */
  const waiting = new Set<() => void>();
  const channel = openChannel();

  const fresh = (): boolean =>
    token !== null && !stale && Date.now() < token.expiresAtMs - REFRESH_LEAD_MS - HANDOUT_SLACK_MS;

  function hold(value: string, expiresAtMs: number): void {
    token = { value, expiresAtMs };
    stale = false;
    signedOut = false;
    clearTimeout(timer);
    const due = expiresAtMs - REFRESH_LEAD_MS - Date.now();
    timer = setTimeout(() => void begin(), Math.min(Math.max(due, MIN_DELAY_MS), MAX_DELAY_MS));
  }

  function set(bundle: TokenBundle): void {
    if (!isBundle(bundle)) return;
    const expiresAtMs = Date.now() + bundle.expires_in * 1000;
    hold(bundle.access_token, expiresAtMs);
    channel?.postMessage({ accessToken: bundle.access_token, expiresAtMs });
  }

  /** A sibling's bundle: its rotation revoked the token held here, so it takes that one's place. */
  function receive(data: unknown): void {
    if (!isRecord(data)) return;
    const { accessToken: value, expiresAtMs } = data;
    if (typeof value !== "string" || !B64TOKEN.test(value) || value === token?.value) return;
    if (typeof expiresAtMs !== "number" || !Number.isFinite(expiresAtMs)) return;
    if (expiresAtMs <= Date.now()) return;
    hold(value, expiresAtMs);
    for (const done of waiting) done();
  }
  if (channel !== null) channel.onmessage = (event: MessageEvent<unknown>) => receive(event.data);

  /** `true` once a sibling's bundle is held, `false` if none comes within `SIBLING_WAIT_MS`. */
  function siblingBundle(): Promise<boolean> {
    return new Promise((resolve) => {
      const finish = (held: boolean): void => {
        clearTimeout(timeout);
        waiting.delete(done);
        resolve(held);
      };
      const done = (): void => finish(true);
      const timeout = setTimeout(() => finish(false), SIBLING_WAIT_MS);
      waiting.add(done);
    });
  }

  function clear(): void {
    token = null;
    stale = false;
    signedOut = true;
    ended += 1;
    clearTimeout(timer);
  }

  function endSession(): void {
    clear();
    toSignIn();
  }

  /** `POST /auth/refresh`, never aborted; `keepalive`: a reload or a closed tab still stores the rotated cookie. */
  function present(): Promise<Response> {
    const csrf = readCsrfCookie();
    return fetch(REFRESH_PATH, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: csrf === null ? {} : { [CSRF_HEADER]: csrf },
    });
  }

  /** SR-041 recovery: `GET /auth/session`, identified by the `cv_refresh` cookie alone, re-issues the CSRF one. */
  async function reissueCsrf(): Promise<boolean> {
    const before = readCsrfCookie();
    await fetch(SESSION_PATH, { credentials: "same-origin" });
    const after = readCsrfCookie();
    return after !== null && after !== before;
  }

  async function post(askedWith: string | null): Promise<RefreshOutcome> {
    if (fresh()) return "ok"; // a bundle arrived while this call waited for the lock
    // the CSRF cookie rotates with the session: it changed while this call waited, so a sibling rotated,
    // and the bundle it posts is held instead of rotating (and revoking) once more
    if (channel !== null && readCsrfCookie() !== askedWith && (await siblingBundle())) return "ok";
    const session = ended;
    let res = await present();
    // SR-041 refuses before the cookie is spent, so it is presented once more with a re-issued CSRF cookie
    if (res.status === 403 && (await codeOf(res)) === CSRF_REFUSED && (await reissueCsrf())) {
      res = await present();
    }
    const body: unknown = res.ok || res.status === 401 ? await res.json().catch(() => null) : null;
    if (session !== ended) return "lost"; // the session ended here meanwhile: its successor is not held
    if (res.ok) {
      const bundle = tokensOf(body);
      if (!isBundle(bundle)) return "failed";
      set(bundle);
      return "ok";
    }
    if (res.status !== 401) return "failed";
    if (isRecord(body) && body["code"] === IDLE_LOCKED) return "locked";
    // a page load that finds no session leaves the route guard to send the user to sign-in
    if (token === null) clear();
    else endSession();
    return "lost";
  }

  /** The tab's one refresh, shared by every caller while it runs, under the cross-tab lock; never rejects. */
  function begin(): Promise<RefreshOutcome> {
    if (inFlight === null) {
      const askedWith = readCsrfCookie();
      inFlight = exclusive(() => post(askedWith))
        .catch((): RefreshOutcome => "failed") // unreachable or not JSON: the next ask tries again
        .finally(() => {
          inFlight = null;
        });
    }
    return inFlight;
  }

  /** The token to repeat a call refused with `rejected` (or with none), or `null`: one refresh at most. */
  async function renewAfter(
    rejected: string | undefined,
    signal: AbortSignal | null | undefined,
  ): Promise<string | null> {
    if (token !== null && token.value !== rejected) return token.value; // renewed here or by a sibling
    if (signedOut) return null; // the session ended: nothing to renew
    stale = true;
    return (await waitFor(begin(), signal)) === "ok" ? (token?.value ?? null) : null;
  }

  /** Whether a new token may cure `res`: a 401 but an idle lock's, or a CSRF refusal of the bearer sent. */
  async function renewable(res: Response, bearer: boolean): Promise<boolean> {
    if (res.status === 401) return (await codeOf(res)) !== IDLE_LOCKED;
    return bearer && res.status === 403 && (await codeOf(res)) === CSRF_REFUSED;
  }

  async function adopt(res: Response): Promise<Response> {
    if (res.ok) {
      try {
        const bundle = tokensOf(await res.clone().json());
        if (isBundle(bundle)) set(bundle);
      } catch {
        // no JSON body: nothing to hold
      }
    }
    return res;
  }

  return {
    set,
    clear,
    endSession,
    refresh: () => waitFor(begin()),
    async getToken(): Promise<TokenResult> {
      if (signedOut) return { kind: "unavailable" };
      const outcome = fresh() ? "ok" : await waitFor(begin());
      if (outcome === "locked") return { kind: "locked" };
      return outcome === "ok" && token !== null
        ? { kind: "ok", accessToken: token.value, expiresAtMs: token.expiresAtMs }
        : { kind: "unavailable" };
    },
    invalidate(): void {
      stale = true;
    },
    async send(input, init, transport) {
      const path = apiPath(input);
      if (path === null) return transport(init);
      const attempt = (value: string | undefined): Promise<Response> =>
        transport(value === undefined ? init : withBearer(input, init, value));
      // a call that mints or rotates a session must not race a refresh: it runs under the lock with the
      // token of that moment (none to a pre-session call), and its bundle is held before the lock is let go
      if (MINTING.has(path)) {
        return exclusive(async () =>
          adopt(await attempt(PRE_SESSION.has(path) ? undefined : token?.value)),
        );
      }
      const sent = token?.value;
      let res = await attempt(sent);
      // a 401, or a CSRF refusal of a bearer a sibling's rotation revoked, means the server did nothing:
      // one renewal, then the call once more
      const repeatable = !path.startsWith(AUTH_PREFIX) || AUTH_REPEATABLE.has(path);
      if (repeatable && (await renewable(res, sent !== undefined))) {
        const next = await renewAfter(sent, init.signal);
        init.signal?.throwIfAborted(); // the caller stopped waiting: as `fetch` would, it is told so
        if (next !== null) res = await attempt(next);
      }
      if (path === LOGOUT_PATH && res.ok) clear(); // the session ended: the caller routes
      return res;
    },
  };
}

/** SCR-001, carrying where the user was, as the route guard does (`routes/guards.ts`). */
function goToSignIn(): void {
  const { pathname, search } = window.location;
  window.location.assign(`${SIGN_IN_PATH}?next=${encodeURIComponent(pathname + search)}`);
}

/** The tab's holder: the HTTP clients, the WS client (`startShell`) and the auth responses share it. */
export const accessToken = createAccessTokenHolder(goToSignIn);
