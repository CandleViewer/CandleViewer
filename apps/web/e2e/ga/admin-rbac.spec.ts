import {
  concretePath,
  DENIAL_HEADINGS,
  expectSettledOutcome,
  ROUTE_EXPECTATIONS,
} from "@candleviewer/fixtures/e2e";
import type { Page } from "@playwright/test";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { json, stubSession } from "../support/api";
import { expect, test } from "./fixtures";

// E49-Q01 (#1335) Gherkin "RBAC boundaries are asserted negatively", for the admin and owner-only
// routes this build ships (R-1xx/R-3xx; most are placeholders that name their owning epic).
//
// What this spec proves, and only this: the CLIENT. As a viewer and as a manager, every route the
// role is refused renders the 403/404 state and the page sends no privileged call (no mutating
// call other than the session's own /auth calls, nothing under /api/v1/admin): it fails on the
// request, whatever the page then shows. The owner positive control opens the same routes as the
// owner against a stand-in that allows them, and asserts each renders, so a route broken for
// everyone cannot pass as "refused". The stand-in server below refuses privileged calls itself,
// so this spec never reaches a server's decision.
//
// The SERVER's refusal of each privileged action, per role, is proven below E2E, by the backend
// RBAC suites: services/api/tests/contract/rbac/test_route_matrix.py (every served operation x
// every actor against matrix.yaml, refusals never successes) and services/api/tests/security/admin/
// (the admin abuse catalogue). The privileged actions on admin screens that have no UI yet are
// carried rows (docs/qa/ga-coverage-gaps.json, E42 and E27); no admin story is tagged covered here.

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const DENIAL_PAGES = new Set(["R-900", "R-901"]); // the 403 and 404 pages themselves
/** SCR-154: the 403 state renders within 200 ms (14-screens-catalogue.md). The smoke allows 3x on
 * shared CI runners and takes the best of three navigations, so one scheduling stall on a busy
 * runner cannot fail it; the screen's budget itself is unchanged (BQ-13). */
const SCR_154_BUDGET_MS = 200;
const CI_MULTIPLIER = 3;
const SCR_154_TRIES = 3;

type Refusing = "manager" | "viewer";
const refused = (role: Refusing) =>
  ROUTE_MANIFEST.filter((r) => {
    const outcome = ROUTE_EXPECTATIONS[r.id]?.[role];
    return !DENIAL_PAGES.has(r.id) && (outcome === "forbidden" || outcome === "not-found");
  });

/** Every API call the page makes; privileged ones are recorded, and refused with 403 unless the
 * stand-in plays an allowing server (the owner control). */
async function standIn(page: Page, allow = false): Promise<string[]> {
  const privileged: string[] = [];
  // Registered before stubSession, so the session's own stubs answer first (newest route wins).
  await page.route("**/api/v1/**", (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const isSessionCall = path.startsWith("/api/v1/auth/");
    if (path.startsWith("/api/v1/admin") || (MUTATING.has(req.method()) && !isSessionCall)) {
      privileged.push(`${req.method()} ${path}`);
      if (!allow) return route.fulfill(json({ title: "Forbidden", status: 403 }, 403));
    }
    return route.fulfill(json({ items: [] }));
  });
  return privileged;
}

for (const role of ["viewer", "manager"] as const)
  test(`@plan-GA-RBAC-1 as a ${role}, every refused route sends no privileged call @ga-regression @ga-area-admin`, async ({
    page,
  }) => {
    const routes = refused(role);
    expect(routes.length, `the manifest refuses the ${role} no route`).toBeGreaterThan(0);
    const privileged = await standIn(page);
    await stubSession(page, { role });
    for (const route of routes) {
      const outcome = ROUTE_EXPECTATIONS[route.id]?.[role];
      await page.goto(concretePath(route.path));
      const heading =
        outcome === "forbidden" ? DENIAL_HEADINGS.forbidden : DENIAL_HEADINGS["not-found"];
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    }
    expect(privileged, "a refused role's page sent a privileged call").toEqual([]);
  });

test("@plan-GA-RBAC-3 owner control: the routes refused to a viewer or a manager render for the owner @ga-regression @ga-area-admin", async ({
  page,
}) => {
  const ids = new Set([...refused("viewer"), ...refused("manager")].map((r) => r.id));
  const routes = ROUTE_MANIFEST.filter(
    (r) => ids.has(r.id) && ROUTE_EXPECTATIONS[r.id]?.owner === "render",
  );
  expect(routes.length, "no refused route renders for the owner").toBeGreaterThan(0);
  await standIn(page, true);
  await stubSession(page, { role: "owner" });
  for (const route of routes) {
    const requested = concretePath(route.path);
    await page.goto(requested);
    await expectSettledOutcome(page, requested, "render");
    for (const heading of [DENIAL_HEADINGS.forbidden, DENIAL_HEADINGS["not-found"]])
      await expect(page.getByRole("heading", { level: 1, name: heading })).toHaveCount(0);
  }
});

test("@plan-GA-RBAC-2 SCR-154 smoke: a viewer's in-app navigation to an owner-only route renders the 403 state in budget @ga-regression @ga-area-admin @perf-smoke", async ({
  page,
}, testInfo) => {
  const target = refused("viewer").find((r) => ROUTE_EXPECTATIONS[r.id]?.viewer === "forbidden");
  expect(target, "no owner-only route answers a viewer with 403").toBeDefined();
  const privileged = await standIn(page);
  await stubSession(page, { role: "viewer" });
  const timings: number[] = [];
  for (let attempt = 0; attempt < SCR_154_TRIES; attempt += 1) {
    await page.goto("/settings/profile");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // In-page (no reload): push the route, then time until the 403 heading is in the DOM.
    timings.push(
      await page.evaluate(
        async ({ path, heading }) => {
          const shown = () =>
            [...document.querySelectorAll("h1")].some((h) => h.textContent?.trim() === heading);
          const t0 = performance.now();
          window.history.pushState({}, "", path);
          window.dispatchEvent(new PopStateEvent("popstate"));
          while (!shown()) {
            if (performance.now() - t0 > 10_000) return Number.POSITIVE_INFINITY;
            await new Promise((r) => requestAnimationFrame(r));
          }
          return performance.now() - t0;
        },
        { path: concretePath(target?.path ?? "/"), heading: DENIAL_HEADINGS.forbidden },
      ),
    );
  }
  // The measured values ride the report (watch them in the first nights' flake table).
  testInfo.annotations.push({ type: "scr-154-ms", description: timings.join(", ") });
  expect(Math.min(...timings)).toBeLessThanOrEqual(SCR_154_BUDGET_MS * CI_MULTIPLIER);
  expect(privileged).toEqual([]);
});
