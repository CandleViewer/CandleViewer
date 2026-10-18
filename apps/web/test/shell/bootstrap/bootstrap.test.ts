import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, resetSharedThemeStores } from "@candleviewer/ui";
import {
  BOOTSTRAP_TIMEOUT_MS,
  SLOW_BOOT_THRESHOLD_MS,
  runBootstrap,
} from "../../../src/shell/bootstrap/bootstrap.js";
import { getShellState, resetShellState } from "../../../src/shell/bootstrap/store.js";
import { getMeClaims, resetMeClaims } from "../../../src/lib/auth/meCache.js";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

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

  it("issues exactly one request each to /me, /me/preferences and /me/keymap, in parallel", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      calls.push(path);
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/preferences")
        return Promise.resolve(jsonResponse({ appearance: { theme: "dark" } }));
      return Promise.resolve(jsonResponse({ bindings: [] }));
    });
    await runBootstrap({ fetchImpl });
    expect(calls.sort()).toEqual(["/api/v1/me", "/api/v1/me/keymap", "/api/v1/me/preferences"]);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("sets the environment from /me and never assumes a default before it resolves", async () => {
    expect(getShellState().environment).toBe("unknown");
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().environment).toBe("demo");
  });

  it("populates the me-claims cache route guards read", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getMeClaims()).toMatchObject({ authenticated: true, role: "owner" });
  });

  it("sets bootstrap to failed with http_error reason on a /me 500", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
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

  it("proceeds with defaults and a warning when preferences fails, without failing the whole boot", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
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
