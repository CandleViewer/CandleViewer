import { concretePath, expectSettledOutcome } from "@candleviewer/fixtures/e2e";
import type { Page } from "@playwright/test";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { stubSession } from "../support/api";
import { seriousAxe } from "../support/axe";
import { expect, test } from "../shell/fixtures";
import { ADMIN_EXCEPTIONS, isAdminPath, unguardedAdminRoutes } from "./adminRoutes";

// E42-Q02 (#1215) part 1: AD-S01-02's client half on the stub lane [BQ-6]. Every `/admin` route
// of the router's own manifest, walked as a manager and as a viewer: the 404 any unknown route
// shows, word for word and with the same page title, with no admin code loaded and no admin or
// users call made (D02 D6; one guard path for both, `routes/guards.ts`). A route added without
// the guard fails the first test here, and the walk visits it. R-360 is the one closed exception
// (`adminRoutes.ts`). The server half, each admin read refused by role, is E42-X03's matrix. Behind
// the shell suite's egress guard, the API stubbed at the network layer (C-13.5).

/** The admin area's lazy chunk (`admin-shell.spec.ts`): Vite names it after `AdminArea.tsx`. */
const ADMIN_CHUNK = /\/AdminArea-[^/]+\.js$/u;
const ADMIN_CALL = /^\/api\/v1\/(?:admin|users)(?:\/|$)/u;
const UNKNOWN = "/admin/zzz-unknown";

/** Every path the page asks for from now on: its scripts and its `/api/v1/` calls. */
function watchPaths(page: Page): () => string[] {
  const paths: string[] = [];
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  return () => paths;
}

/** The 404 at `path`: its title and its surface's text (CMP-090), the path it echoes masked. */
async function notFoundCopy(page: Page, path: string): Promise<string> {
  await page.goto(path);
  // A test's first page load boots the SPA, which a loaded runner can take seconds over: wait for
  // the 404 itself first, so the settle check that follows times the landing, not the boot.
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible({
    timeout: 15_000,
  });
  await expectSettledOutcome(page, path, "not-found");
  const text = await page.locator('[data-cmp="CMP-090"]').innerText();
  return `${await page.title()}\n${text}`.replaceAll(path, "{path}");
}

test("E42-Q02 AD-S01-02 every /admin route in the router's manifest carries the admin guard", () => {
  expect(unguardedAdminRoutes(ROUTE_MANIFEST)).toEqual([]);
});

const walked = ROUTE_MANIFEST.filter((e) => isAdminPath(e.path) && !(e.id in ADMIN_EXCEPTIONS));

for (const route of walked)
  for (const role of ["manager", "viewer"] as const)
    test(`E42-Q02 AD-S01-02 ${route.id} as ${role}: an unknown route's 404, no admin code or call`, async ({
      page,
    }) => {
      const paths = watchPaths(page);
      await stubSession(page, { role });
      const unknown = await notFoundCopy(page, UNKNOWN);
      expect(await notFoundCopy(page, concretePath(route.path))).toBe(unknown);
      expect(paths()).toContain("/api/v1/me"); // positive control: the watcher sees the SPA's reads
      expect(paths().filter((p) => ADMIN_CHUNK.test(p) || ADMIN_CALL.test(p))).toEqual([]);
    });

for (const [id, excepted] of Object.entries(ADMIN_EXCEPTIONS))
  for (const role of ["manager", "viewer"] as const) {
    const outcome = excepted.roles.includes(role) ? "render" : "forbidden";
    test(`E42-Q02 AD-S01-02 ${id} as ${role}, the closed exception: ${outcome}`, async ({
      page,
    }) => {
      const route = ROUTE_MANIFEST.find((e) => e.id === id);
      expect(route, `${id} is in the manifest`).toBeDefined();
      await stubSession(page, { role });
      const requested = concretePath(route?.path ?? "");
      await page.goto(requested);
      await expectSettledOutcome(page, requested, outcome);
    });
  }

test("E42-Q02 AD-S01-02 the admin 404 has no serious axe violation", async ({ page }) => {
  await stubSession(page, { role: "manager" });
  await notFoundCopy(page, "/admin");
  expect(await seriousAxe(page)).toEqual([]);
});
