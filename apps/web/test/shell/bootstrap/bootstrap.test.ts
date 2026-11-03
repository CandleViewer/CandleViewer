import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, resetSharedThemeStores } from "@candleviewer/ui";
import {
  BOOTSTRAP_TIMEOUT_MS,
  SLOW_BOOT_THRESHOLD_MS,
  runBootstrap,
} from "../../../src/shell/bootstrap/bootstrap.js";
import { getShellState, resetShellState } from "../../../src/shell/bootstrap/store.js";
import { REFRESH_SENT_KEY, accessToken } from "../../../src/lib/auth/accessToken.js";
import {
  CLAIMS_MAX_AGE_MS,
  getMeClaims,
  refreshMeClaims,
  resetMeClaims,
} from "../../../src/lib/auth/meCache.js";
import {
  VIEW_AS_PATH,
  VIEW_AS_READ_TIMEOUT_MS,
  resetViewAs,
} from "../../../src/lib/auth/viewAsContext.js";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** `GET /auth/session/view-as` (E42-S03): `204`, the session views as no one. */
const noViewAs = (): Response => new Response(null, { status: 204 });

const ME_BODY = {
  user: { id: "u1", username: "owner", email: "o@example.com", roles: ["owner"], status: "active" },
  role: "owner",
  permissions: ["rules:author"],
  accounts: [],
  session: { session_id: "s1", environment: "demo", elevated_until: null },
};

describe("runBootstrap", () => {
  beforeEach(() => {
    resetShellState();
    resetMeClaims();
  });
  afterEach(() => resetViewAs());

  it("issues exactly one request each to /me, /me/preferences, /me/keymap and the view-as context, in parallel", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      calls.push(path);
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me/preferences")
        return Promise.resolve(jsonResponse({ appearance: { theme: "dark" } }));
      return Promise.resolve(jsonResponse({ bindings: [] }));
    });
    const booting = runBootstrap({ fetchImpl });
    expect(calls).toHaveLength(4); // all four sent before any answer is read
    await booting;
    expect(calls.sort()).toEqual([
      "/api/v1/auth/session/view-as",
      "/api/v1/me",
      "/api/v1/me/keymap",
      "/api/v1/me/preferences",
    ]);
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
  });

  it("sets the environment from /me and never assumes a default before it resolves", async () => {
    expect(getShellState().environment).toBe("unknown");
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().environment).toBe("demo");
  });

  it("populates the me-claims cache route guards read", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getMeClaims()).toMatchObject({ authenticated: true, role: "owner" });
  });

  // #5405: the registered reader re-reads `/me` past the bound and keeps the shell in step.
  it("registers a /me reader that updates the claims, the shell's me and its environment", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date("2026-11-02T00:00:00Z"));
      let body: unknown = ME_BODY;
      const fetchImpl = vi.fn().mockImplementation((path: string) => {
        if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
        if (path === "/api/v1/me") return Promise.resolve(jsonResponse(body));
        return Promise.resolve(jsonResponse({}));
      });
      await runBootstrap({ fetchImpl });
      body = {
        ...ME_BODY,
        role: "viewer",
        user: { ...ME_BODY.user, roles: ["viewer"] },
        session: { ...ME_BODY.session, environment: "live" },
      };
      vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
      await refreshMeClaims();
      expect(fetchImpl.mock.calls.filter(([p]) => p === "/api/v1/me")).toHaveLength(2);
      expect(getMeClaims()).toMatchObject({ authenticated: true, role: "viewer" });
      expect(getShellState().me).toMatchObject({ role: "viewer" });
      expect(getShellState().environment).toBe("live");
    } finally {
      vi.useRealTimers();
    }
  });

  // #5405: the re-read is quiet; a lost session is the reader's answer, never the holder's route. Only
  // a refresh that finds the session lost signs it out: one that fails or finds it locked keeps the claims.
  const lost = (): Promise<Response> =>
    Promise.resolve(jsonResponse({ code: "refresh_token_invalid" }, 401));
  it.each<[string, string, () => Promise<Response>, boolean, boolean]>([
    ["a revoked session", "session_revoked", lost, false, false],
    ["an expired token whose refresh finds the session lost", "token_expired", lost, false, false],
    [
      "an expired token whose refresh fails on the network",
      "token_expired",
      () => Promise.reject(new TypeError("Failed to fetch")),
      true,
      false,
    ],
    [
      "an expired token whose refresh answers a 5xx",
      "token_expired",
      () => Promise.resolve(jsonResponse({ code: "unavailable" }, 503)),
      true,
      false,
    ],
    [
      "an expired token whose refresh finds the session idle-locked",
      "token_expired",
      () => Promise.resolve(jsonResponse({ code: "session_idle_locked" }, 401)),
      true,
      true,
    ],
    ["an idle lock", "session_idle_locked", lost, true, true],
  ])(
    "the /me reader on %s: a sign-out sets no claims and routes nothing; a blip or a lock keeps them",
    async (_name, code, refresh, kept, locked) => {
      vi.useFakeTimers({ toFake: ["Date"] });
      const assign = vi.fn();
      const onLocked = vi.fn();
      const unsubscribe = accessToken.onLocked(onLocked);
      const { origin } = window.location;
      vi.stubGlobal("location", {
        origin,
        href: `${origin}/terminal/last`,
        pathname: "/terminal/last",
        search: "",
        assign,
      });
      vi.stubGlobal("fetch", vi.fn(refresh));
      try {
        vi.setSystemTime(new Date("2026-11-02T00:00:00Z"));
        let revoked = false;
        const fetchImpl = vi.fn().mockImplementation((path: string) => {
          if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
          if (path !== "/api/v1/me") return Promise.resolve(jsonResponse({}));
          return Promise.resolve(revoked ? jsonResponse({ code }, 401) : jsonResponse(ME_BODY));
        });
        await runBootstrap({ fetchImpl });
        accessToken.set({ access_token: "probe-held-x", token_type: "Bearer", expires_in: 600 });
        revoked = true;
        vi.setSystemTime(Date.now() + CLAIMS_MAX_AGE_MS);
        await refreshMeClaims();
        expect(getMeClaims()).toMatchObject(
          kept ? { authenticated: true, role: "owner" } : { authenticated: false },
        );
        expect(assign).not.toHaveBeenCalled();
        expect(onLocked.mock.calls.length > 0).toBe(locked); // the SCR-005 overlay's cue
      } finally {
        unsubscribe();
        accessToken.clear();
        localStorage.removeItem(REFRESH_SENT_KEY); // the mark of a refresh no test answered
        vi.unstubAllGlobals();
        vi.useRealTimers();
      }
    },
  );

  it("sets bootstrap to failed with http_error reason on a /me 500", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse({}, 500));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual({
      kind: "failed",
      reason: "http_error",
      status: 500,
    });
    expect(getShellState().environment).toBe("unknown");
  });

  it.each([
    ["session_idle_locked", { kind: "locked" }],
    ["unauthenticated", { kind: "failed", reason: "http_error", status: 401 }],
  ])("a /me 401 %s sets bootstrap to %j, with no claims (#1640)", async (code, phase) => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse({ status: 401, code }, 401));
      return Promise.resolve(jsonResponse({}, 401));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual(phase);
    expect(getMeClaims().authenticated).toBe(false);
  });

  it("proceeds with defaults and a warning when preferences fails, without failing the whole boot", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/preferences") return Promise.resolve(jsonResponse({}, 500));
      return Promise.resolve(jsonResponse({ bindings: [] }));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
    expect(getShellState().preferencesWarning).toBeTruthy();
  });

  it("proceeds with a warning when keymap fails — a broken keymap must not block login", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/keymap") return Promise.resolve(jsonResponse({}, 500));
      return Promise.resolve(jsonResponse({ appearance: {} }));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
    expect(getShellState().keymapWarning).toBeTruthy();
  });

  it("marks bootstrap as slow after SLOW_BOOT_THRESHOLD_MS while /me is still pending", async () => {
    vi.useFakeTimers();
    let resolveMe!: (value: Response) => void;
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") {
        return new Promise<Response>((resolve) => {
          resolveMe = resolve;
        });
      }
      return Promise.resolve(jsonResponse({}));
    });
    const pending = runBootstrap({ fetchImpl });
    await vi.advanceTimersByTimeAsync(SLOW_BOOT_THRESHOLD_MS);
    expect(getShellState().bootstrap).toEqual({ kind: "slow" });
    resolveMe(jsonResponse(ME_BODY));
    await vi.runAllTimersAsync();
    await pending;
    vi.useRealTimers();
  });

  it("exposes the bootstrap timeout constant used for each call", () => {
    expect(BOOTSTRAP_TIMEOUT_MS).toBeGreaterThan(0);
  });
});

// E42-S03 (SCR-124): the view-as context is the shell's read-only state, read beside `/me` before
// anything mounts (22 `getViewAs`). Only a 204 or a context read is an answer: anything else fails
// the boot as `/me`'s failure does, with no claims and no `me`, so no writable shell mounts.
describe("runBootstrap: the view-as read (E42-S03)", () => {
  const CONTEXT = {
    target_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
    target_username: "alex",
    target_display_name: null,
    started_at: "2026-09-14T10:00:00Z",
    expires_at: "2026-09-14T10:30:00Z",
    read_only: true,
    state: "active",
  };
  /** `/me`, preferences and keymap answer as a signed-in owner; the view-as read as `viewAs`. */
  const boot = (viewAs: () => Promise<Response>, me: () => Promise<Response> = ok(ME_BODY)) =>
    vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return viewAs();
      if (path === "/api/v1/me") return me();
      return Promise.resolve(jsonResponse({}));
    });
  function ok(body: unknown, status = 200): () => Promise<Response> {
    return () => Promise.resolve(jsonResponse(body, status));
  }

  beforeEach(() => {
    resetShellState();
    resetMeClaims();
  });
  afterEach(() => {
    resetViewAs();
    vi.useRealTimers();
  });

  it("boots with no context on a 204", async () => {
    await runBootstrap({ fetchImpl: boot(() => Promise.resolve(noViewAs())) });
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
    expect(getShellState().viewAs).toEqual({ kind: "none" });
  });

  it("boots into a live context: the target's /me, and the context in the store with it", async () => {
    await runBootstrap({ fetchImpl: boot(ok(CONTEXT)) });
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
    expect(getShellState().viewAs).toMatchObject({
      kind: "held",
      targetName: "alex",
      state: "active",
    });
    expect(getMeClaims().authenticated).toBe(true);
  });

  it("is the held boot for a context the server ended, whose /me is refused view_as_expired", async () => {
    const refused = ok({ status: 403, code: "view_as_expired" }, 403);
    await runBootstrap({ fetchImpl: boot(ok({ ...CONTEXT, state: "expired" }), refused) });
    expect(getShellState().bootstrap).toEqual({ kind: "held" });
    expect(getShellState().viewAs).toMatchObject({ kind: "held", state: "expired" });
    expect([getShellState().me, getMeClaims().authenticated]).toEqual([null, false]);
  });

  it.each<[string, () => Promise<Response>, object]>([
    [
      "a 503",
      ok({ status: 503, code: "store_unavailable" }, 503),
      { reason: "http_error", status: 503 },
    ],
    [
      "a network error",
      () => Promise.reject(new TypeError("Failed to fetch")),
      { reason: "unknown" },
    ],
    ["a 200 that is no context", ok({}), { reason: "unknown" }],
    ["an unknown state", ok({ ...CONTEXT, state: "paused" }), { reason: "unknown" }],
    ["a 404 (no stub, no route)", ok({}, 404), { reason: "http_error", status: 404 }],
  ])("fails the boot closed on %s: no claims, no me, no context", async (_name, viewAs, failed) => {
    await runBootstrap({ fetchImpl: boot(viewAs) });
    expect(getShellState().bootstrap).toEqual({ kind: "failed", ...failed });
    expect(getShellState().viewAs).toEqual({ kind: "unknown" });
    expect([getShellState().me, getShellState().environment]).toEqual([null, "unknown"]);
    expect(getMeClaims().authenticated).toBe(false);
  });

  it("fails the boot closed as a timeout when the view-as read is never answered", async () => {
    vi.useFakeTimers();
    const hanging = (_path: string, init?: RequestInit): Promise<Response> =>
      new Promise((_resolve, reject) =>
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        ),
      );
    const fetchImpl = vi.fn().mockImplementation((path: string, init?: RequestInit) => {
      if (path === VIEW_AS_PATH) return hanging(path, init);
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    const booting = runBootstrap({ fetchImpl });
    await vi.advanceTimersByTimeAsync(VIEW_AS_READ_TIMEOUT_MS);
    await booting;
    expect(getShellState().bootstrap).toEqual({ kind: "failed", reason: "timeout" });
    expect(getMeClaims().authenticated).toBe(false);
  });

  it("puts /me's own failure first: an idle lock is SCR-005, whatever the view-as read says", async () => {
    const locked = ok({ status: 401, code: "session_idle_locked" }, 401);
    await runBootstrap({
      fetchImpl: boot(ok({ status: 401, code: "session_idle_locked" }, 401), locked),
    });
    expect(getShellState().bootstrap).toEqual({ kind: "locked" });
  });
});

describe("runBootstrap: theme runtime (#3139)", () => {
  const root = document.documentElement;
  const PREPAINT = {
    "data-theme": "light",
    "data-density": "comfortable",
    "data-motion": "reduce",
    "data-text-scale": "125",
  };
  const attributes = (): Record<string, string | null> =>
    Object.fromEntries(Object.keys(PREPAINT).map((name) => [name, root.getAttribute(name)]));

  /** What the pre-paint snippet leaves on the root for a persisted local override. */
  function persistLocalOverride(): void {
    localStorage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({
        baseTheme: "light",
        matchSystem: false,
        highContrast: false,
        density: "comfortable",
        motionOverride: "on",
        textScale: 125,
      }),
    );
    for (const [name, value] of Object.entries(PREPAINT)) root.setAttribute(name, value);
  }

  function respondWith(preferences: Promise<Response>): typeof fetch {
    return vi.fn().mockImplementation((path: string) => {
      if (path === VIEW_AS_PATH) return Promise.resolve(noViewAs());
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/preferences") return preferences;
      return Promise.resolve(jsonResponse({ bindings: [] }));
    }) as unknown as typeof fetch;
  }

  beforeEach(() => {
    resetShellState();
    resetMeClaims();
    resetSharedThemeStores(); // a store made by an earlier test has not read this test's storage
  });

  afterEach(() => {
    resetViewAs();
    resetSharedThemeStores();
    localStorage.clear();
    for (const name of Object.keys(PREPAINT)) root.removeAttribute(name);
  });

  it("One writer: system theme, spacious density and high contrast reach the root through the runtime", async () => {
    const fetchImpl = respondWith(
      Promise.resolve(
        jsonResponse({
          appearance: { theme: "system", density: "spacious", high_contrast: true },
        }),
      ),
    );
    await runBootstrap({ fetchImpl });
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
    expect(root.getAttribute("data-density")).toBe("comfortable");
  });

  it("feeds the accessibility settings too: reduced motion on and increased contrast on reach the root", async () => {
    const fetchImpl = respondWith(
      Promise.resolve(
        jsonResponse({ accessibility: { reduced_motion: "on", increased_contrast: "on" } }),
      ),
    );
    await runBootstrap({ fetchImpl });
    expect(root.getAttribute("data-motion")).toBe("reduce");
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
  });

  it("No clobber: the persisted values stay on the root until the server values arrive", async () => {
    persistLocalOverride();
    let answer!: (response: Response) => void;
    const slow = new Promise<Response>((resolve) => {
      answer = resolve;
    });
    const done = runBootstrap({ fetchImpl: respondWith(slow) });
    await Promise.resolve();
    await Promise.resolve();
    expect(attributes()).toStrictEqual(PREPAINT);

    answer(jsonResponse({ appearance: { theme: "dark", font_scale: 1.5 } }));
    await done;
    expect(attributes()).toStrictEqual({
      "data-theme": "dark",
      "data-density": "comfortable", // the server sent no density: the persisted one stays
      "data-motion": "reduce",
      "data-text-scale": "150",
    });
  });

  it("keeps the persisted values when preferences fail to load", async () => {
    persistLocalOverride();
    await runBootstrap({ fetchImpl: respondWith(Promise.resolve(jsonResponse({}, 500))) });
    expect(getShellState().preferencesWarning).toBeTruthy();
    expect(attributes()).toStrictEqual(PREPAINT);
  });

  it("does not persist what the server sent", async () => {
    const before = localStorage.getItem(THEME_STORAGE_KEY);
    await runBootstrap({
      fetchImpl: respondWith(Promise.resolve(jsonResponse({ appearance: { theme: "light" } }))),
    });
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(before);
  });
});
