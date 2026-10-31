import { describe, expect, it } from "vitest";
import { ROLES, ROUTE_EXPECTATIONS } from "@candleviewer/fixtures/e2e";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { evaluateAccess } from "../../src/routes/rbac";

// E10-Q02: the role matrix's expectations table (e2e/shell/role-matrix.spec.ts) against the route
// manifest, in seconds rather than in the E2E lane: a new route without a declared outcome fails
// here first, and a declared outcome that contradicts the route's access rule fails too.

describe("ROUTE_EXPECTATIONS", () => {
  it("declares an outcome for exactly the manifest's route ids", () => {
    expect(Object.keys(ROUTE_EXPECTATIONS).sort()).toEqual(ROUTE_MANIFEST.map((r) => r.id).sort());
  });

  it.each(ROUTE_MANIFEST.map((r) => [r.id, r] as const))(
    "%s: a role the access rule denies is declared with that denial",
    (_id, route) => {
      for (const role of ROLES) {
        const decision = evaluateAccess(route.access, {
          authenticated: true,
          role,
          permissions: [],
        });
        const declared = ROUTE_EXPECTATIONS[route.id]?.[role];
        if (decision.kind === "deny")
          expect(declared).toBe(decision.as === "404" ? "not-found" : "forbidden");
        else expect(declared).toBeDefined();
      }
    },
  );
});
