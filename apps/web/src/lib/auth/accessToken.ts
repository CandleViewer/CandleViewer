/**
 * #2712: the tab's access token (ADR-0020 decisions 1, 3 and 5; `23-ws-protocol.md` §4.3).
 *
 * - Held in this closure only: never in storage, a cookie, a URL, a log or an error message.
 * - `send` gives it as `Authorization: Bearer` to same-origin `/api/v1/` URLs and to nothing else.
 * - It is refreshed at `expires_at - 60 s` through `POST /auth/refresh` (the `cv_refresh` cookie and the
 *   CSRF header): one refresh at a time in the tab, and across tabs under the `cv.auth.refresh` Web Lock,
 *   because the refresh cookie is single-use and presenting a spent one revokes the session family.
 * - The WS client reads it through `getToken`: `ok`, `locked` (`401 session_idle_locked`; nothing is
 *   cleared) or `unavailable`. Any other `401` from the refresh, or `endSession` (logout), forgets it and
 *   routes to sign-in (SCR-001).
 */
import type { ErrorCode, generated } from "@candleviewer/protocol";
import { CSRF_HEADER, readCsrfCookie } from "../http/csrfCookie";
import type { TokenResult, TokenSource } from "../ws/api";

export type TokenBundle = generated.rest.components["schemas"]["TokenBundle"];
export type RefreshOutcome = "ok" | "locked" | "lost" | "failed";
type Transport = (init: RequestInit) => Promise<Response>;

export const REFRESH_PATH = "/api/v1/auth/refresh";
export const REFRESH_LOCK = "cv.auth.refresh";
export const SIGN_IN_PATH = "/login";
/** 23 §4.3: the token is renewed at `expires_at - 60 s`; `getToken` never hands one out inside that minute. */
export const REFRESH_LEAD_MS = 60_000;
/** A refresh that does not answer by then fails: the shell's first paint waits for the page-load one. */
export const REFRESH_TIMEOUT_MS = 10_000;
const API_PREFIX = "/api/v1/";
const AUTH_PREFIX = "/api/v1/auth/";
const IDLE_LOCKED: ErrorCode = "session_idle_locked";
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
/** RFC 6750 `b64token`: what `Headers` takes as it is, so the value never ends up in a `TypeError`. */
const B64TOKEN = /^[A-Za-z0-9\-._~+/]+=*$/;

export interface AccessTokenHolder extends TokenSource {
  /** Holds a bundle from sign-in, MFA, step-up or refresh; it expires `expires_in` s after receipt. */
  set(bundle: TokenBundle): void;
  /** Forgets the token: `getToken` answers `unavailable` until the next `set`. */
  clear(): void;
  /** Logout or a lost session: forgets the token and routes to sign-in. */
  endSession(): void;
  /** One refresh, shared by every caller while it runs; never rejects. */
  refresh(): Promise<RefreshOutcome>;
  /** Sends with the bearer to a same-origin API URL; a 401 refreshes and repeats once; holds bundles. */
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

/** The path of a same-origin `/api/v1/` URL, else `null`: another origin, or no URL, gets no bearer. */
function apiPath(input: RequestInfo | URL): string | null {
  const { origin } = window.location;
  try {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, origin);
    const same = origin !== "null" && url.origin === origin;
    return same && url.pathname.startsWith(API_PREFIX) ? url.pathname : null;
  } catch {
    return null;
  }
}

function withBearer(input: RequestInfo | URL, init: RequestInit, token: string): RequestInit {
  // `init.headers` replaces a Request's own, so those are carried over
  const headers = new Headers(
    init.headers ?? (input instanceof Request ? input.headers : undefined),
  );
  headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

/** Runs `task` under the cross-tab lock; a browser without Web Locks has the in-tab single flight only. */
async function exclusive<T>(task: () => Promise<T>): Promise<T> {
  const locks: LockManager | undefined = navigator.locks;
  return locks === undefined ? task() : locks.request(REFRESH_LOCK, task);
}

export function createAccessTokenHolder(toSignIn: () => void): AccessTokenHolder {
  let token: { readonly value: string; readonly expiresAtMs: number } | null = null;
  /** The WS client or a `401` reported it rejected: the next ask refreshes. */
  let stale = false;
  /** A refresh found no session, or it ended: `unavailable` without asking again, until a `set`. */
  let signedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight: Promise<RefreshOutcome> | null = null;

  const fresh = (): boolean =>
    token !== null && !stale && Date.now() < token.expiresAtMs - REFRESH_LEAD_MS;

  function set(bundle: TokenBundle): void {
    if (!isBundle(bundle)) return;
    const now = Date.now();
    token = { value: bundle.access_token, expiresAtMs: now + bundle.expires_in * 1000 };
    stale = false;
    signedOut = false;
    clearTimeout(timer);
    const due = token.expiresAtMs - REFRESH_LEAD_MS - now;
    timer = setTimeout(() => void refresh(), Math.min(Math.max(due, MIN_DELAY_MS), MAX_DELAY_MS));
  }

  function clear(): void {
    token = null;
    stale = false;
    signedOut = true;
    clearTimeout(timer);
  }

  function endSession(): void {
    clear();
    toSignIn();
  }

  async function post(): Promise<RefreshOutcome> {
    if (fresh()) return "ok"; // a bundle arrived while this call waited for the lock
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), REFRESH_TIMEOUT_MS);
    try {
      const csrf = readCsrfCookie();
      const res = await fetch(REFRESH_PATH, {
        method: "POST",
        credentials: "include",
        headers: csrf === null ? {} : { [CSRF_HEADER]: csrf },
        signal: abort.signal,
      });
      if (res.ok) {
        const bundle = tokensOf(await res.json());
        if (!isBundle(bundle)) return "failed";
        set(bundle);
        return "ok";
      }
      if (res.status !== 401) return "failed";
      const body: unknown = await res.json().catch(() => undefined);
      if (isRecord(body) && body["code"] === IDLE_LOCKED) return "locked";
      // a page load that finds no session leaves the route guard to send the user to sign-in
      if (token === null) clear();
      else endSession();
      return "lost";
    } catch {
      return "failed"; // unreachable, too slow or not JSON: nothing is cleared, and the next ask tries again
    } finally {
      clearTimeout(timeout);
    }
  }

  function refresh(): Promise<RefreshOutcome> {
    inFlight ??= exclusive(post)
      .catch((): RefreshOutcome => "failed")
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  }

  /** The token to repeat a call with after it was refused with `rejected`, or `null`. */
  async function renewAfter(rejected: string): Promise<string | null> {
    if (token === null) return null; // the session ended meanwhile
    if (token.value !== rejected) return token.value; // another call renewed it already
    stale = true;
    return (await refresh()) === "ok" ? (token?.value ?? null) : null;
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
    refresh,
    async getToken(): Promise<TokenResult> {
      if (signedOut) return { kind: "unavailable" };
      const outcome = fresh() ? "ok" : await refresh();
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
      // token of that moment, and its bundle is held before the lock is let go
      if (MINTING.has(path)) return exclusive(async () => adopt(await attempt(token?.value)));
      const sent = token?.value;
      const res = await attempt(sent);
      // a 401 means the server did nothing: one refresh, then the call once more. An auth route's 401
      // judges a password or a code, and repeating it would count a second failure.
      if (sent === undefined || res.status !== 401 || path.startsWith(AUTH_PREFIX)) return res;
      const next = await renewAfter(sent);
      return next === null ? res : attempt(next);
    },
  };
}

/** The tab's holder: the HTTP clients, the WS client (`startShell`) and the auth responses share it. */
export const accessToken = createAccessTokenHolder(() => window.location.assign(SIGN_IN_PATH));
