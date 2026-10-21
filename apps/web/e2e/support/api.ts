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

export interface LeakGuard {
  /** Awaits every pending body check, then fails if any forbidden value was seen (SR-012). */
  readonly flush: () => Promise<void>;
}

/** Records response bodies the page receives and fails on any forbidden value. */
export function watchForLeaks(page: Page, forbidden: readonly string[]): LeakGuard {
  const leaks: string[] = [];
  const pending: Promise<void>[] = [];
  page.on("response", (res) => {
    pending.push(
      res
        .text()
        .then((t) => {
          for (const f of forbidden)
            if (t.includes(f)) leaks.push(`${res.url()} leaked a ${f.length}-char value`);
        })
        .catch(() => undefined),
    );
  });
  return {
    flush: async () => {
      await Promise.all(pending);
      if (leaks.length > 0) throw new Error(leaks.join("; "));
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
