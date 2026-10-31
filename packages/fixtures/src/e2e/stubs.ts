import { expect, type Page, type Request, type Route } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";

type Schemas = generated.rest.components["schemas"];

// Network-layer stubs shared by the web and Electron E2E suites (E09-Q02, moved here by E10-Q02):
// no live backend (C-13.5). App code is not mocked.
export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => ({
  status,
  contentType: "application/json",
  headers,
  body: JSON.stringify(body),
});

export interface MeOptions {
  readonly role: "owner" | "manager" | "viewer";
  readonly elevatedUntil?: () => string | null;
}

/** `GET /settings` as `22-api-openapi.yaml` `getSettings` answers it: its `effective` example. */
export const SETTINGS: Schemas["Settings"] = {
  appearance: {
    theme: "dark",
    density: "compact",
    font_scale: 1,
    reduce_motion: false,
    high_contrast: false,
  },
  chart: {
    default_bar_type: "time",
    default_param: "1",
    crosshair_sync: true,
    bar_close_countdown: true,
    price_scale_mode: "logarithmic",
  },
  orderflow: {
    heatmap_bid_colour: "#2FA37A",
    heatmap_ask_colour: "#D2504B",
    imbalance_ratio: 3,
    min_stack: 3,
    value_area_pct: 70,
    big_trade_threshold_mode: "relative",
    big_trade_k: 7,
  },
  trading: {
    one_click_armed: false,
    arm_timeout_seconds: 300,
    confirm_market_orders: true,
    confirm_flatten: true,
    default_environment: "demo",
    default_qty_presets: ["0.01", "0.05", "0.1", "0.25"],
  },
  notifications: {
    desktop_enabled: true,
    email_enabled: false,
    webhook_url: null,
    quiet_hours: null,
  },
  data: { default_depth: 200, stale_badge_after_ms: 2000, max_history_bars: 100000 },
  _meta: {
    overridden: ["appearance.density", "trading.default_qty_presets"],
    updated_at: "2026-09-13T19:02:00Z",
  },
};

/**
 * `GET /auth/session` as 22 `authGetSession` answers it (its `manager` example), for `role` with the empty
 * permissions `/me` gives here, an empty `account_scope`, and without the optional `kill_switch`, `clock_offset_ms`
 * and `api_version`: unlocked, 15 min from the idle lock, so `SessionLockHost` reads it again only 14 min on.
 */
export function sessionInfo(role: MeOptions["role"]): Schemas["SessionInfo"] {
  return {
    user: {
      id: "11111111-2222-3333-4444-555555555555",
      username: "viewer.alice",
      email: "alice@example.com",
      roles: [role],
      status: "active",
      mfa_enabled: true,
      mfa_required: true,
    },
    permissions: [],
    account_scope: [],
    server_time: "2026-09-14T10:31:02.114Z",
    session: {
      id: "5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f",
      issued_at: "2026-09-14T10:24:00Z",
      expires_at: "2026-09-14T20:05:00Z",
      idle_deadline: "2026-09-14T10:46:02Z",
      idle_timeout_s: 900,
      locked: false,
    },
  };
}

/** Answers `GET` to `path` with `body`; any other method goes on to the routes before it, or the network. */
async function stubGet(page: Page, path: string, body: () => unknown): Promise<void> {
  await page.route(
    (url) => url.pathname === path,
    (r) => (r.request().method() === "GET" ? r.fulfill(json(body())) : r.fallback()),
  );
}

/** Stub the session bootstrap calls the shell makes for an authenticated user. */
export async function stubSession(page: Page, opts: MeOptions): Promise<void> {
  // #2712: a page load re-derives the in-memory access token from `cv_refresh` before the shell's
  // first authenticated call, so a signed-in server answers the refresh with a token bundle. Without
  // it every call waits out the holder's guard for a refresh that may have spent the cookie.
  await page.route("**/api/v1/auth/refresh", (r: Route) =>
    r.fulfill(
      json({
        status: "authenticated",
        tokens: {
          access_token: ["e2e", "stub", "bearer"].join("."), // opaque, like the server's
          token_type: "Bearer",
          expires_in: 600,
          refresh_expires_in: 2_592_000,
        },
      }),
    ),
  );
  await page.route("**/api/v1/me", (r: Route) =>
    r.fulfill(
      json({
        role: opts.role,
        permissions: [],
        session: { environment: "demo", elevated_until: opts.elevatedUntil?.() ?? null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  // The shell's own calls after its first paint: the settings (`PreferencesProvider`), the session
  // (`SessionLockHost`) and, every 2 s, the liveness probe (`liveness.ts`). Unstubbed, `vite preview`
  // answers each with the SPA's index.html.
  await stubGet(page, "/api/v1/settings", () => SETTINGS);
  await stubGet(page, "/api/v1/auth/session", () => sessionInfo(opts.role));
  await stubGet(page, "/api/v1/health/live", () => ({ status: "ok" })); // 22 `getLiveness`
}

/**
 * `GET /auth/sessions` as services/api/candleviewer/api/sessions.py answers it: `_view_json` rows
 * (every field, `current` on the caller's) in one page. The first row is the current session.
 */
export function sessionsPage(): unknown {
  const view = (n: number, current: boolean, device: string | null) => ({
    id: `00000000-0000-4000-8000-00000000000${n}`,
    device_name: device,
    ip: "100.64.0.7",
    user_agent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
    created_at: "2026-10-27T08:00:00+00:00",
    last_seen_at: "2026-10-27T09:00:00+00:00",
    expires_at: "2026-10-27T20:00:00+00:00",
    current,
  });
  const items = [view(2, true, null), view(3, false, "Desktop app")];
  return { items, meta: { next_cursor: null, has_more: false, count: items.length } };
}

/** Answers `GET /auth/sessions` (any cursor or limit) with `sessionsPage()`. */
export async function stubSessionsList(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === "/api/v1/auth/sessions",
    (r) => r.fulfill(json(sessionsPage())),
  );
}

export interface LeakGuard {
  /**
   * Waits for the page's `/api/v1/` requests to settle, awaits every pending body check, then fails if any
   * forbidden value was seen (SR-012), if any body could not be read, or if a request had not settled by the
   * bound (fail closed): only a redirect's body, a static file's `304` and a failed request's are passed over.
   */
  readonly flush: () => Promise<void>;
}

/** How long `flush` waits for the page's `/api/v1/` requests to finish or fail before it fails on them. */
export const SETTLE_MS = 5_000;

const apiCall = (request: Request): string =>
  `${request.method()} ${new URL(request.url()).pathname}`;

/**
 * Checks the response bodies the page receives, and those only (not request bodies, headers or cookies, not
 * WebSocket frames, not other pages' or workers' requests), and fails on any forbidden value. It reads a body once
 * its request has finished, never on the `response` event.
 *
 * `flush` judges only once every `/api/v1/` request the page has started has finished or failed, waiting up to
 * `settleMs` (a web-first poll):
 * - a request that failed (aborted, or cancelled by a navigation) delivered no body the page could read, so it
 *   is not checked;
 * - a request still unsettled at the bound fails the flush, which names it;
 * - a finished request whose body cannot be read fails the flush, so "read nothing" never passes as "found
 *   nothing" (fail closed). Of the finished ones, only a redirect, which has no body, is passed over. A `304`
 *   hands the page its cached copy, which Playwright cannot read: from the API it fails the flush, and from a
 *   static file (the SPA's own build, revalidated on the next page load) it is passed over.
 *
 * Other requests (scripts, styles) are checked once finished but not waited for: a shared worker's script never
 * finishes for the page. A flush sees only the requests started before its wait ends. Playwright reads a body
 * lazily, a navigation drops the bodies not yet read, and a request it cancels may never settle at all: so a test
 * flushes before a navigation of its own, once the page has made the requests it means to check, and gives each
 * navigation a page of its own when the page may start one after the flush (a timer's).
 */
export function watchForLeaks(
  page: Page,
  forbidden: readonly string[],
  { settleMs = SETTLE_MS }: { readonly settleMs?: number } = {},
): LeakGuard {
  if (forbidden.some((f) => f === ""))
    throw new Error("an empty forbidden value matches every body");
  const leaks: string[] = [];
  const unread: string[] = [];
  const pending: Promise<void>[] = [];
  /** The page's `/api/v1/` requests that have started and neither finished nor failed. */
  const inflight = new Set<Request>();
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/")) inflight.add(request);
  });
  page.on("requestfailed", (request) => {
    inflight.delete(request); // no body the page could read
  });
  page.on("requestfinished", (request) => {
    inflight.delete(request);
    const where = apiCall(request);
    // never rejects: whatever stops a read lands in `unread`, which `flush` fails on
    const check = async (): Promise<void> => {
      let status = 0;
      let text: string;
      try {
        const res = await request.response();
        status = res?.status() ?? 0;
        const cached = status === 304 && new URL(request.url()).pathname.startsWith("/api/v1/");
        if (status >= 300 && status <= 399 && !cached) return; // a redirect, or the SPA's own file
        if (res === null) throw new Error("no response");
        text = await res.text();
      } catch {
        unread.push(`${where} (${status}): its body was not read, so not checked`);
        return;
      }
      for (const f of forbidden)
        if (text.includes(f)) leaks.push(`${request.url()} leaked a ${f.length}-char value`);
    };
    pending.push(check());
  });
  return {
    flush: async () => {
      await expect
        .poll(() => [...inflight].map(apiCall), {
          message: "requests still unsettled at the flush, so their bodies were not checked",
          timeout: settleMs,
        })
        .toEqual([]);
      await Promise.all(pending);
      if (leaks.length + unread.length > 0) throw new Error([...leaks, ...unread].join("; "));
    },
  };
}

/** No forbidden value in localStorage, sessionStorage, the URL or readable cookies (SR-012). */
export async function assertNoClientSecrets(
  page: Page,
  forbidden: readonly string[],
): Promise<void> {
  // The page's globals, typed here: this package also compiles under the Electron suite's Node-only lib.
  const where = await page.evaluate(() => {
    const w = globalThis as unknown as {
      localStorage: object;
      sessionStorage: object;
      location: { href: string };
      document: { cookie: string };
    };
    return {
      local: JSON.stringify({ ...w.localStorage }),
      session: JSON.stringify({ ...w.sessionStorage }),
      url: w.location.href,
      cookie: w.document.cookie,
    };
  });
  for (const [name, text] of Object.entries(where))
    for (const f of forbidden)
      if (text.includes(f)) throw new Error(`${name} contains a forbidden ${f.length}-char value`);
}
