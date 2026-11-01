import {
  concretePath,
  expectSettledOutcome,
  ROLES,
  ROUTE_EXPECTATIONS,
} from "@candleviewer/fixtures/e2e";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { stubSession } from "../support/api";
import { expect, test } from "../ga/fixtures";

// E10-Q02 role matrix (plan step RM-1): every route of the manifest × the three roles, generated
// from the manifest itself, so a new route joins the matrix on its own and fails here until its
// outcome is declared in ROUTE_EXPECTATIONS (@candleviewer/fixtures/e2e). The client's rendering
// decision only; the server's enforcement is proven by the backend RBAC tests (C-12.4).

for (const route of ROUTE_MANIFEST)
  for (const role of ROLES)
    test(`@plan-RM-1 ${route.id} ${route.path} as ${role} @ga-regression @ga-area-admin`, async ({
      page,
    }) => {
      const expected = ROUTE_EXPECTATIONS[route.id]?.[role];
      expect(expected, `${route.id} has no declared outcome for ${role}`).toBeDefined();
      await stubSession(page, { role });
      const requested = concretePath(route.path);
      await page.goto(requested);
      await expectSettledOutcome(page, requested, expected);
    });
