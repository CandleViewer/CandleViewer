import type { Page, Route } from "@playwright/test";

// Network-layer stubs shared by the E09-Q02 specs (no live backend, C-13.5). App code is not mocked.
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
   * Awaits every pending body check, then fails if any forbidden value was seen (SR-012), or if any body could
   * not be read (fail closed): only a redirect's, which has none, is passed over.
   */
  readonly flush: () => Promise<void>;
}

/**
 * Checks the response bodies the page receives, and those only (not request bodies, headers or cookies, not
 * WebSocket frames, not other pages' or workers' requests), and fails on any forbidden value. It reads a body once
 * its request has finished, never on the `response` event: a request a navigation cancels never finishes and its
 * `text()` never settles, so `flush` would wait on it until the test timed out (nothing reached the page, so
 * nothing is checked). It fails closed: a finished request whose body it cannot read fails the flush, so "read
 * nothing" never passes as "found nothing". Playwright reads a body lazily and the page drops it on navigating
 * away, so a test flushes before a navigation of its own.
 */
export function watchForLeaks(page: Page, forbidden: readonly string[]): LeakGuard {
  if (forbidden.some((f) => f === ""))
    throw new Error("an empty forbidden value matches every body");
  const leaks: string[] = [];
  const unread: string[] = [];
  const pending: Promise<void>[] = [];
  page.on("requestfinished", (request) => {
    const where = `${request.method()} ${new URL(request.url()).pathname}`;
    // never rejects: whatever stops a read lands in `unread`, which `flush` fails on
    const check = async (): Promise<void> => {
      let status = 0;
      let text: string;
      try {
        const res = await request.response();
        status = res?.status() ?? 0;
        if (status >= 300 && status <= 399) return; // a redirect has no body to leak
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
  const where = await page.evaluate(() => ({
    local: JSON.stringify({ ...window.localStorage }),
    session: JSON.stringify({ ...window.sessionStorage }),
    url: window.location.href,
    cookie: document.cookie,
  }));
  for (const [name, text] of Object.entries(where))
    for (const f of forbidden)
      if (text.includes(f)) throw new Error(`${name} contains a forbidden ${f.length}-char value`);
}
