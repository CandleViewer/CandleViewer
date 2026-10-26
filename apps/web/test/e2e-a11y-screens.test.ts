// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { PR_IDS, SCREENS, SIGNED_IN_SCREENS } from "../e2e/a11y/screens";
import { ROUTE_MANIFEST } from "../src/routes/manifest";
import { evaluateAccess, type MeClaims } from "../src/routes/rbac";

/**
 * #3470: the a11y collectors enter a screen with a bare `page.goto` and wait for any <main>. A
 * guarded route visited without a session is bounced to /login, whose own <main> satisfies that
 * wait, so the login page would be audited under the route's id and the gate would pass without
 * ever seeing the route. These tests pin the two lists that prevent it: the PR set holds public
 * routes only, and a guarded screen is entered through a session stub that its route allows.
 */
const route = (id: string) => ROUTE_MANIFEST.find((e) => e.id === id);
const signedIds = SIGNED_IN_SCREENS.map((s) => s.id);

describe("the a11y gate's screen set (#3470)", () => {
  afterEach(() => void vi.unstubAllEnvs());

  it("holds only routes that render without a session in the PR set", () => {
    expect([...PR_IDS].filter((id) => route(id)?.access.roles !== "public")).toEqual([]);
  });

  it("enters each signed-in screen as a role its guarded route allows, and names its h1", () => {
    for (const { id, signedIn } of SIGNED_IN_SCREENS) {
      const access = route(id)?.access;
      expect(access, `${id} is in the route manifest`).toBeDefined();
      expect(access?.roles, `${id} is guarded`).not.toBe("public");
      // The claims the shell builds from the /me stub: no step-up, no permissions.
      const claims: MeClaims = {
        authenticated: true,
        role: signedIn?.role ?? null,
        permissions: [],
      };
      const decision = access && evaluateAccess(access, claims);
      expect(decision, `${id}: the guard lets the stub in`).toEqual({ kind: "allow" });
      expect(signedIn?.heading.trim(), `${id} names its h1`).toBeTruthy();
    }
  });

  it("never lists a screen in both the PR set and the signed-in set", () => {
    expect(signedIds.filter((id) => PR_IDS.has(id))).toEqual([]);
    expect(SCREENS.filter((s) => signedIds.includes(s.id))).toEqual([]);
  });

  it("keeps a signed-in screen out of the nightly full sweep too", async () => {
    vi.stubEnv("A11Y_SWEEP", "full");
    vi.resetModules();
    const full = await import("../e2e/a11y/screens");
    expect(full.SCREENS.length).toBeGreaterThan(PR_IDS.size);
    expect(full.SCREENS.filter((s) => signedIds.includes(s.id))).toEqual([]);
  });

  it("audits the appearance settings (R-203) as a signed-in owner screen", () => {
    expect(SIGNED_IN_SCREENS).toContainEqual({
      id: "R-203",
      path: "/settings/appearance",
      signedIn: { role: "owner", heading: "Appearance" },
    });
  });
});
