import { readFileSync } from "node:fs";
import {
  concretePath,
  expectSettledOutcome,
  ROLES,
  ROUTE_EXPECTATIONS,
} from "@candleviewer/fixtures/e2e";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { stubSession } from "../support/api";
import { expect, test } from "./fixtures";

// The claims `/me` carries for each role: the server's grants (`role_permissions` of the generated
// RBAC seed, the owner's `*` expanded to every code, as db/seed.py does), so a screen that reads its
// own permission (SCR-090's `alerts:read`) decides as it does for that role, not on empty claims.
const SEED = JSON.parse(
  readFileSync(
    new URL("../../../../services/api/candleviewer/auth/rbac_seed.json", import.meta.url),
    "utf8",
  ),
) as {
  readonly permissions: readonly { readonly code: string }[];
  readonly role_permissions: Readonly<Record<string, readonly string[]>>;
};
const claims = (role: string): readonly string[] => {
  const granted = SEED.role_permissions[role] ?? [];
  return granted.includes("*") ? SEED.permissions.map((p) => p.code) : granted;
};

// E10-Q02 role matrix (plan step RM-1): every route of the manifest × the three roles, generated
// from the manifest itself, so a new route joins the matrix on its own and fails here until its
// outcome is declared in ROUTE_EXPECTATIONS (@candleviewer/fixtures/e2e). The client's rendering
// decision only; the server's enforcement is proven by the backend RBAC tests (C-12.4).

for (const route of ROUTE_MANIFEST)
  for (const role of ROLES)
    test(`@plan-RM-1 ${route.id} ${route.path} as ${role}`, async ({ page }) => {
      const expected = ROUTE_EXPECTATIONS[route.id]?.[role];
      expect(expected, `${route.id} has no declared outcome for ${role}`).toBeDefined();
      await stubSession(page, { role });
      // Registered after stubSession's, so this answer wins (Playwright matches the newest route first).
      await page.route("**/api/v1/me", (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            role,
            permissions: claims(role),
            session: { environment: "demo", elevated_until: null },
          }),
        }),
      );
      const requested = concretePath(route.path);
      await page.goto(requested);
      await expectSettledOutcome(page, requested, expected);
    });
