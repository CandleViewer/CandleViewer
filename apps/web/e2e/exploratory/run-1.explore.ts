import type { Page } from "@playwright/test";
import { concretePath } from "@candleviewer/fixtures/e2e";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { json, stubSession } from "../support/api";
import { REFRESH_INVALID } from "../support/contexts";
import { focused, heading, test, type SessionLog } from "./harness";

// E49-Q02 (#1336) run 1: the first exploratory session on what main has built, against a fresh
// `dist/` on recorded-shape stubs (no backend, no exchange). Oracles are the charters' own ids
// (docs/qa/charters/E49-charter-*.md). Nothing here asserts: each probe notes what it saw, and the
// run record (docs/qa/e49-run-1-findings.md) dispositions every `suspect`.

const DENIED = new Set(["Page not found", "You don't have access to this"]);
const BADGE = "Trading environment: Demo";
/** Absolute, so a `//`-led path stays a path and is never read as a protocol-relative host. */
const ORIGIN = `http://127.0.0.1:${process.env["CV_EXPLORE_PORT"] ?? "4174"}`;

/** How a probe landed: its path and level-1 heading, and whether a guarded screen showed. */
async function land(page: Page, path: string): Promise<{ at: string; h1: string }> {
  await page.goto(`${ORIGIN}${path}`);
  const h1 = await heading(page);
  return { at: new URL(page.url()).pathname, h1 };
}

/** Counts the page's `/api/v1/admin/**` calls (O7.2: a denied route fetches none of its data). */
async function countAdminCalls(page: Page): Promise<() => number> {
  let n = 0;
  await page.route("**/api/v1/admin/**", (r) => {
    n += 1;
    return r.fulfill(json({ items: [] }));
  });
  return () => n;
}

/** Odd spellings of one deep link: the guard must deny every one the router would match. */
const variants = (p: string): readonly string[] => [
  p,
  `${p}/`,
  p.toUpperCase(),
  `/${p}`,
  `${p}?role=owner`,
  `${p};x=1`,
  p.replace(/\/([a-z])(?=[^/]*$)/u, (_m, c: string) => `/%${c.charCodeAt(0).toString(16)}`),
  `${p}/.`,
  `/x/..${p}`,
];

const GUARDED: readonly { path: string; denyFor: readonly ("manager" | "viewer")[] }[] = [
  { path: "/admin/users", denyFor: ["manager", "viewer"] },
  { path: "/admin/keys/x1/rotate", denyFor: ["manager", "viewer"] },
  { path: "/admin/flags", denyFor: ["manager", "viewer"] },
  { path: "/admin/audit", denyFor: ["viewer"] },
  { path: "/risk", denyFor: ["manager", "viewer"] },
  { path: "/trade-groups/new", denyFor: ["manager", "viewer"] },
  { path: "/rules/new", denyFor: ["viewer"] },
];

function judgeDenied(log: SessionLog, role: string, path: string, r: { at: string; h1: string }) {
  // Only a denial heading counts: a stub or a built screen under any other heading is suspect.
  const shown = !DENIED.has(r.h1);
  log.note({
    step: `deep link ${path}`,
    route: r.at,
    role,
    oracle: "O7.1",
    result: shown ? "suspect" : "ok",
    note: `landed ${r.at} with h1 "${r.h1}"`,
  });
}

test.describe("C7 admin and RBAC probing", () => {
  test.use({ charter: "C7" });

  test("deep-link spellings of guarded routes as manager and viewer", async ({ page, log }) => {
    const adminCalls = await countAdminCalls(page);
    for (const role of ["manager", "viewer"] as const) {
      await stubSession(page, { role });
      for (const g of GUARDED.filter((x) => x.denyFor.includes(role)))
        for (const v of variants(g.path)) judgeDenied(log, role, v, await land(page, v));
    }
    log.note({
      step: "admin data fetched while denied",
      route: "-",
      role: "manager+viewer",
      oracle: "O7.2",
      result: adminCalls() === 0 ? "ok" : "suspect",
      note: `${adminCalls()} /api/v1/admin calls`,
    });
  });

  test("nav rail and Alt+digit reach for each role", async ({ page, log }) => {
    for (const role of ["owner", "manager", "viewer"] as const) {
      await stubSession(page, { role });
      await land(page, "/settings/appearance");
      const rail = page.getByRole("navigation").first();
      const admin = await rail.getByRole("link", { name: /Admin/u }).count();
      log.note({
        step: "Admin item in the nav rail",
        route: "/settings/appearance",
        role,
        oracle: "O7.3",
        result: (role === "owner") === admin > 0 ? "ok" : "suspect",
        note: `${admin} Admin link(s)`,
      });
      await page.keyboard.press("Alt+7");
      const h1 = await heading(page);
      const at = new URL(page.url()).pathname;
      log.note({
        step: "Alt+7 (the Admin digit)",
        route: at,
        role,
        oracle: "O7.3",
        result: role !== "owner" && /^R-3/u.test(h1) ? "suspect" : "ok",
        note: `landed ${at} with h1 "${h1}"`,
      });
    }
  });

  test("signed out: deep links after sign-out", async ({ page, log }) => {
    await page.route("**/api/v1/auth/refresh", (r) => r.fulfill(REFRESH_INVALID));
    await page.route("**/api/v1/me", (r) => r.fulfill(json({ status: 401 }, 401)));
    for (const path of ["/admin/users", "/terminal/x1", "/settings/profile", "/rules/x1/graph"]) {
      const r = await land(page, path);
      log.note({
        step: `signed-out deep link ${path}`,
        route: r.at,
        role: "anonymous",
        oracle: "O7.5",
        result: r.at.startsWith("/login") ? "ok" : "suspect",
        note: `landed ${r.at} with h1 "${r.h1}"`,
      });
    }
  });

  test("view-as impersonation (SCR-124)", async ({ page, log }) => {
    await stubSession(page, { role: "owner" });
    const r = await land(page, "/admin/users/x1");
    const viewAs = await page.getByRole("button", { name: /view as/iu }).count();
    log.note({
      step: "look for a view-as control on the user detail",
      route: r.at,
      role: "owner",
      oracle: "O7.6",
      result: "info",
      note: viewAs === 0 ? "not built: no view-as control (E42)" : `${viewAs} control(s)`,
    });
  });
});

test.describe("C8 cross-feature: every route for every role", () => {
  test.use({ charter: "C8" });

  for (const role of ["owner", "manager", "viewer"] as const)
    test(`environment badge and landing, all ${ROUTE_MANIFEST.length} routes, ${role}`, async ({
      page,
      log,
    }) => {
      await stubSession(page, { role });
      for (const route of ROUTE_MANIFEST) {
        const path = concretePath(route.path);
        const r = await land(page, path);
        const badge = await page.getByRole("img", { name: BADGE }).count();
        const chromeless = ["/login", "/invite", "/offline", "/maintenance", "/404"].some((p) =>
          r.at.startsWith(p),
        );
        log.note({
          step: `${route.id} ${path}`,
          route: r.at,
          role,
          oracle: "O8.1",
          result: badge > 0 || chromeless ? "ok" : "suspect",
          note: `h1 "${r.h1}", badge ${badge}`,
        });
        // O8.2 writes a note only when it fails; silence means it held.
        if (r.h1 === "")
          log.note({
            step: `${route.id} ${path}`,
            route: r.at,
            role,
            oracle: "O8.2",
            result: "suspect",
            note: "no level-1 heading after 10 s",
          });
      }
    });
});

test.describe("keyboard-only segment (03 §12)", () => {
  test.use({ charter: "KB" });

  const SCREENS: readonly { path: string; role: "owner" | null }[] = [
    { path: "/login", role: null },
    { path: "/settings/appearance", role: "owner" },
    { path: "/settings/hotkeys", role: "owner" },
    { path: "/settings/profile", role: "owner" },
    { path: "/admin/users/new", role: "owner" },
    { path: "/terminal/x1", role: "owner" },
    { path: "/404", role: "owner" },
  ];

  for (const s of SCREENS)
    test(`Tab sweep ${s.path}`, async ({ page, log }) => {
      if (s.role === null)
        await page.route("**/api/v1/auth/refresh", (r) => r.fulfill(REFRESH_INVALID));
      else await stubSession(page, { role: s.role });
      await land(page, s.path);
      const seen: string[] = [];
      let stuck = 0;
      for (let i = 0; i < 60; i += 1) {
        await page.keyboard.press("Tab");
        const f = await focused(page);
        if (f === seen.at(-1)) stuck += 1;
        seen.push(f);
        if (seen.length > 3 && f === seen[0]) break; // wrapped round
      }
      const unique = new Set(seen);
      const noRing = [...unique].filter((f) => f.endsWith("(no ring)"));
      log.note({
        step: "focus order",
        route: s.path,
        role: s.role ?? "anonymous",
        oracle: "none",
        result: "info",
        note: seen.join(" > ").slice(0, 2000),
      });
      log.note({
        step: `Tab x${seen.length}`,
        route: s.path,
        role: s.role ?? "anonymous",
        oracle: "O-KB.1",
        result: stuck > 2 || unique.size < 2 ? "suspect" : "ok",
        note: `${unique.size} stops, ${stuck} repeats, body ${seen.filter((f) => f === "body").length}x`,
      });
      log.note({
        step: "visible focus at each stop",
        route: s.path,
        role: s.role ?? "anonymous",
        oracle: "O-KB.2",
        result: noRing.length > 0 ? "suspect" : "ok",
        note: noRing.length > 0 ? `no ring: ${noRing.slice(0, 3).join(" | ")}` : "all stops ringed",
      });
    });
});
