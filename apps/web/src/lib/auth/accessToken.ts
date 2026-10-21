/**
 * #2712: the access token (ADR-0020 decisions 1, 3 and 5; `23-ws-protocol.md` §4.3).
 *
 * - Held in memory only: never in storage, a cookie, a URL, a log or an error message.
 * - One token per origin. The server keeps one live access token per session: a refresh or a step-up
 *   revokes the one before as `rotated`. So a bundle a tab receives is posted to its same-origin siblings
 *   over the `cv.auth.token` BroadcastChannel (memory to memory, never storage), and each holds it in
 *   place of the older token that rotation revoked. A tab whose session ends (a logout's `2xx`, a refresh
 *   or probe that finds it lost, `endSession`) tells its siblings: each forgets the token without telling
 *   further, and one that held it routes to sign-in.
 * - `send` gives it as `Authorization: Bearer` to same-origin `/api/v1/` URLs and to nothing else.
 * - It is refreshed at `expires_at - 60 s` through `POST /auth/refresh` (the `cv_refresh` cookie and the
 *   CSRF header): one refresh at a time in the tab, and across tabs under the `cv.auth.refresh` Web Lock,
 *   because the refresh cookie is single-use and presenting a spent one revokes the session family. For
 *   the same reason a refresh once sent is never aborted: a caller stops waiting after `REFRESH_WAIT_MS`,
 *   the refresh goes on, and the bundle it gets is held. A tab that closes or reloads lets go of the lock
 *   but not of its refresh, so the next holder may find a spent cookie: `REFRESH_SENT_KEY` narrows that
 *   window, and only a server leeway closes it (README, known gaps).
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
export const SIBLING_WAIT_MS = 1_000;
/**
 * Set while a refresh is on the wire, to the time it was sent (never the token: ADR-0020 decision 1 keeps
 * the credential out of storage), and removed once its answer shows what became of the cookie. A tab that
 * closes or reloads leaves it, as do a lost answer and a `5xx` (which may follow the rotation), so the next
 * lock holder does not present a cookie that refresh may have spent, however long ago it was sent. Only
 * `present`'s answers remove it: a probe that finds the cookie spent leaves it on purpose, so the page load
 * after that sign-out probes again instead of presenting the cookie.
 */
export const REFRESH_SENT_KEY = "cv.auth.refresh_sent_at";
/**
 * How long that holder waits for the cookie a refresh sent less than `REFRESH_WAIT_MS` ago may still
 * store, before it asks the server (about an older one it asks at once).
 */
export const ORPHAN_WAIT_MS = 2_000;
const ORPHAN_POLL_MS = 100;
/**
 * The refresh refusals that come before any rotation, so the cookie in the jar is still the one presented
 * (a `2xx` stores its successor). Any other answer may follow a rotation whose cookie never landed.
 */
const UNROTATED: ReadonlySet<number> = new Set([401, 403, 429]);
/** How long an idle lock a refresh found is answered without the cookie being presented again. */
const LOCKED_MEMO_MS = 5_000;
const SESSION_PATH = "/api/v1/auth/session";
const LOGOUT_PATH = "/api/v1/auth/logout";
const UNLOCK_PATH = "/api/v1/auth/unlock";
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
  /**
   * Forgets the token, here and in the sibling tabs (one that held it routes to sign-in): `getToken`
   * answers `unavailable` until the next bundle; a refresh on the wire is dropped.
   */
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

/**
 * Runs `task` under the cross-tab lock; a browser without Web Locks has the in-tab single flight only.
 * A caller's `call` stops waiting for the lock when its signal aborts or after `REFRESH_WAIT_MS`, and is
 * rejected as `fetch` would reject it: nothing is sent before the grant, so nothing is lost.
 */
async function exclusive<T>(task: () => Promise<T>, call?: RequestInit): Promise<T> {
  const locks: LockManager | undefined = navigator.locks;
  if (locks === undefined) return task();
  if (call === undefined) return locks.request(REFRESH_LOCK, task);
  const { signal } = call;
  const wait = new AbortController();
  const stop = (): void =>
    wait.abort(
      signal?.aborted === true
        ? signal.reason
        : new DOMException("the cv.auth.refresh lock was not granted in time", "TimeoutError"),
    );
  const timeout = setTimeout(stop, REFRESH_WAIT_MS);
  signal?.addEventListener("abort", stop);
  if (signal?.aborted === true) stop();
  const granted = (): void => {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", stop);
  };
  try {
    return await locks.request(REFRESH_LOCK, { signal: wait.signal }, () => {
      granted();
      return task();
    });
  } finally {
    granted();
  }
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

/** Leaves or removes `REFRESH_SENT_KEY`; storage that is blocked or full takes no mark (no guard then). */
function markSent(sent: boolean): void {
  try {
    if (sent) {
      // The mark is a send time, never a token (ADR-0020 Amendment 1): the rule matches the key's name.
      // nosemgrep: no-jwt-in-browser-storage reason=stores-a-send-time-never-a-token owner=@CandleViewer/security review=2027-03-25
      localStorage.setItem(REFRESH_SENT_KEY, String(Date.now()));
    } else localStorage.removeItem(REFRESH_SENT_KEY);
  } catch {
    // no storage for this document
  }
}

/** How long ago a refresh no tab saw answered was sent, or `null`: none, or no storage (no guard then). */
function sentAgo(): number | null {
  try {
    const mark = localStorage.getItem(REFRESH_SENT_KEY);
    return mark === null ? null : Date.now() - Number(mark);
  } catch {
    return null;
  }
}

/**
 * `GET /auth/session` with the cookie alone, made under the lock. It changes no `cv_refresh` cookie and
 * its `401` revokes nothing, so unlike the refresh it is aborted once `REFRESH_WAIT_MS` pass: one that
 * stalled would keep the lock from every tab. The abort rejects it: `begin` answers `failed` and lets the
 * lock go.
 */
async function getSession(): Promise<Response> {
  const abort = new AbortController();
  // a timer, not `AbortSignal.timeout`: the same clock as every other wait here
  const timeout = setTimeout(() => abort.abort(), REFRESH_WAIT_MS);
  try {
    return await fetch(SESSION_PATH, { credentials: "same-origin", signal: abort.signal });
  } finally {
    clearTimeout(timeout);
  }
}

export function createAccessTokenHolder(toSignIn: () => void): AccessTokenHolder {
  let token: { readonly value: string; readonly expiresAtMs: number } | null = null;
  /** The WS client or a refused call reported it rejected: the next ask refreshes. */
  let stale = false;
  /** A refresh found no session, or it ended: `unavailable` without asking again, until a bundle. */
  let signedOut = false;
  /** Counts the sessions this tab ended: a refresh that answers after one is not held. */
  let ended = 0;
  /** Until then an idle lock a refresh found is answered `locked` without presenting the cookie again. */
  let lockedUntil = 0;
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
    lockedUntil = 0;
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

  /**
   * A sibling's bundle, newer than the token held here (its rotation revoked that one, so it takes its
   * place), or its sign-out: the session ended in every tab, so one that held the token routes to sign-in
   * as `lose` does (through `forget`: `clear` or `endSession` would post it back). A tab that held none (the
   * sign-in page, or a page load the route guard sees to) only forgets.
   */
  function receive(data: unknown): void {
    if (!isRecord(data)) return;
    if (data["cleared"] === true) {
      const held = token !== null;
      forget();
      if (held) toSignIn();
      return;
    }
    const { accessToken: value, expiresAtMs } = data;
    if (typeof value !== "string" || !B64TOKEN.test(value) || value === token?.value) return;
    if (typeof expiresAtMs !== "number" || !Number.isFinite(expiresAtMs)) return;
    if (expiresAtMs <= Date.now()) return;
    // every bundle lives as long, so one due no later than the token held was minted before it
    if (token !== null && expiresAtMs <= token.expiresAtMs) return;
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

  /**
   * Forgets the token in this tab. `clear` also tells the sibling tabs, which share the session cookie:
   * each forgets it, and one that held it routes to sign-in.
   */
  function forget(): void {
    token = null;
    stale = false;
    signedOut = true;
    ended += 1;
    lockedUntil = 0;
    clearTimeout(timer);
  }

  function clear(): void {
    forget();
    channel?.postMessage({ cleared: true });
  }

  function endSession(): void {
    clear();
    toSignIn();
  }

  /**
   * The refresh found no session, so no tab has one: the token is forgotten here and in the sibling tabs,
   * and each tab that held it routes to sign-in. A page load, holding none, leaves that to the route guard.
   */
  function lose(): RefreshOutcome {
    if (token === null) clear();
    else endSession();
    return "lost";
  }

  /**
   * `POST /auth/refresh`, never aborted. `keepalive` stores the rotated cookie after a tab closes or
   * reloads, but the lock goes first, so `REFRESH_SENT_KEY` stays until an answer here shows what became of
   * the cookie: a `2xx` or an `UNROTATED` refusal. A lost answer or any other status keeps it.
   */
  async function present(): Promise<Response> {
    const csrf = readCsrfCookie();
    markSent(true);
    const res = await fetch(REFRESH_PATH, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: csrf === null ? {} : { [CSRF_HEADER]: csrf },
    });
    if (res.ok || UNROTATED.has(res.status)) markSent(false); // what became of the cookie is known
    return res;
  }

  /**
   * A refresh no tab saw answered may have spent the cookie in the jar. One sent less than
   * `REFRESH_WAIT_MS` ago (`landing`) may still store its own: that is waited for (`null`: present it). If
   * none lands, or at once for an older one, `GET /auth/session` with the cookie alone tells a live one
   * (`null`) from a spent one (`lost`: that `401` revokes nothing, where a refresh would revoke the family).
   */
  async function orphaned(
    before: string | null,
    landing: boolean,
  ): Promise<"lost" | "failed" | null> {
    // a deadline, not a count of polls: the lock is held meanwhile, and a hidden tab's timers run late
    const deadline = Date.now() + (landing ? ORPHAN_WAIT_MS : 0);
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, ORPHAN_POLL_MS));
      if (readCsrfCookie() !== before) return null; // it landed: the cookie in the jar is the live one
    }
    const res = await getSession();
    if (res.ok) return null;
    return res.status === 401 ? "lost" : "failed";
  }

  /** SR-041 recovery: `GET /auth/session`, identified by the `cv_refresh` cookie alone, re-issues the CSRF one. */
  async function reissueCsrf(): Promise<boolean> {
    const before = readCsrfCookie();
    await getSession();
    const after = readCsrfCookie();
    return after !== null && after !== before;
  }

  async function post(askedWith: string | null): Promise<RefreshOutcome> {
    if (fresh()) return "ok"; // a bundle arrived while this call waited for the lock
    // the CSRF cookie rotates with the session: it changed while this call waited, so a sibling rotated,
    // and the bundle it posts is held instead of rotating (and revoking) once more
    if (channel !== null && readCsrfCookie() !== askedWith && (await siblingBundle())) return "ok";
    // unchanged, but a refresh no tab saw answered (its tab closed or reloaded, letting go of the lock but
    // not of the request, or its answer was lost or a 5xx) may have spent the cookie in the jar, however
    // long ago it was sent
    const age = readCsrfCookie() === askedWith ? sentAgo() : null;
    if (age !== null) {
      const orphan = await orphaned(askedWith, age >= 0 && age < REFRESH_WAIT_MS);
      if (orphan === "lost") return lose();
      if (orphan === "failed") return orphan;
    }
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
    if (isRecord(body) && body["code"] === IDLE_LOCKED) {
      lockedUntil = Date.now() + LOCKED_MEMO_MS;
      return "locked";
    }
    return lose();
  }

  /** The tab's one refresh, shared by every caller while it runs, under the cross-tab lock; never rejects. */
  function begin(): Promise<RefreshOutcome> {
    if (Date.now() < lockedUntil) return Promise.resolve("locked");
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
        return exclusive(
          async () => adopt(await attempt(PRE_SESSION.has(path) ? undefined : token?.value)),
          init,
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
      if (path === UNLOCK_PATH && res.ok) {
        // a live session, unlocked: the next ask refreshes, even in a tab signed out because a locked
        // session's refresh was answered as a lost one (README, known gaps)
        lockedUntil = 0;
        signedOut = false;
      }
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
