import type { Page } from "@playwright/test";
import { concretePath } from "@candleviewer/fixtures/e2e";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { json } from "../support/api";
import { REFRESH_INVALID } from "../support/contexts";
import { heading, tabSweep, test, type SessionLog, type StubRole } from "./harness";
import { callAs, judgeProbe, seededStack, type Probe } from "./seededStack";

// E49-Q02 (#1336) run 2: the rows the scout's BQ-1 marks buildable. Tier A (stubs, socket stub on)
// runs by default; the `@tier-b` sessions run only against `tools/qa/explore_stack.sh`
// (docs/qa/e49-exploratory-harness.md §2), which the config selects by `CV_EXPLORE_RUN_DIR`. As in
// run 1 nothing asserts: each probe notes what it saw and the run record dispositions it.
// Skipped here: the rows the charters park (not built at the pin), and the rows run 1 already did.
// The charters' "Explorable at the pin" tables (docs/qa/charters/) list what is in and out.

const ROLES: readonly StubRole[] = ["owner", "manager", "viewer"];
const DENIED = new Set(["Page not found", "You don't have access to this"]);
const BADGE = "Trading environment: Demo";
const ORIGIN = `http://127.0.0.1:${process.env["CV_EXPLORE_PORT"] ?? "4174"}`;
const TIER_B = { tag: "@tier-b" } as const;

async function land(page: Page, path: string): Promise<{ at: string; h1: string }> {
  await page.goto(`${ORIGIN}${path}`);
  const h1 = await heading(page);
  return { at: new URL(page.url()).pathname, h1 };
}

/** Whether the shell's connection left "Reconnecting" within 5 s (run 1, E49-R1-04). */
async function live(page: Page): Promise<boolean> {
  const chip = page.getByText(/Reconnecting/u).first();
  return chip.waitFor({ state: "hidden", timeout: 5_000 }).then(
    () => true,
    () => false,
  );
}

/** Tier A: the admin reads answer an empty page, so their 404s from the preview are not noted. */
async function stubAdminReads(page: Page): Promise<void> {
  for (const glob of ["**/api/v1/admin/**", "**/api/v1/users/invites"])
    await page.route(glob, (r) => r.fulfill(json({ items: [] })));
}

/** Counts the page's `/api/v1/admin/**` requests from now on (O7.2), answered or not. */
function adminRequests(page: Page): () => number {
  let n = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/v1/admin/")) n += 1;
  });
  return () => n;
}

/** One admin landing for `role`: the Owner's screen is noted, any other role's must be denied. */
function noteAdminLanding(log: SessionLog, role: StubRole, r: { at: string; h1: string }): void {
  const denied = DENIED.has(r.h1);
  log.note({
    step: `open ${r.at}`,
    route: r.at,
    role,
    oracle: role === "owner" ? "none" : "O7.1",
    result: role === "owner" ? "info" : denied ? "ok" : "suspect",
    note: `h1 "${r.h1}"`,
  });
}

/** The admin overview R-300 and the invite screen R-303: what each role is shown. */
async function adminPages(page: Page, log: SessionLog, role: StubRole): Promise<void> {
  const calls = adminRequests(page);
  noteAdminLanding(log, role, await land(page, "/admin"));
  const invite = await land(page, "/admin/users/new");
  noteAdminLanding(log, role, invite);
  if (role === "owner") {
    const roleBox = page.getByRole("combobox", { name: "Role" });
    const offered = (await roleBox.locator("option").allTextContents()).join(", ");
    log.note({
      step: "roles the invite form offers",
      route: invite.at,
      role,
      oracle: "none",
      result: "info",
      note: offered === "" ? "no Role control" : offered,
    });
  } else
    log.note({
      step: "admin data fetched while denied",
      route: "/admin, /admin/users/new",
      role,
      oracle: "O7.2",
      result: calls() === 0 ? "ok" : "suspect",
      note: `${calls()} /api/v1/admin requests`,
    });
}

/** The alerts centre R-190: its heading and whether it renders a body for `role`. */
async function alertsCentre(page: Page, log: SessionLog, role: StubRole): Promise<void> {
  const r = await land(page, "/alerts");
  const tables = await page.getByRole("main").getByRole("table").count();
  const alerts = await page.getByRole("main").getByRole("alert").count();
  log.note({
    step: "open the alerts centre",
    route: r.at,
    role,
    oracle: r.h1 === "" ? "O8.2" : "none",
    result: r.h1 === "" ? "suspect" : "info",
    note: `h1 "${r.h1}", ${tables} table(s), ${alerts} alert message(s)`,
  });
}

// ---------------------------------------------------------------- tier A, socket stub on

for (const role of ROLES)
  test.describe(`C7 admin overview and invite (tier A), ${role}`, () => {
    test.use({ charter: "C7", stubRole: role });

    test("admin overview R-300 and invite R-303", async ({ page, ws, log }) => {
      await stubAdminReads(page);
      await adminPages(page, log, role);
      log.note({
        step: "socket stub",
        route: "-",
        role,
        oracle: "none",
        result: "info",
        note: `${ws.connections()} socket(s), ${ws.authenticated()} authenticated`,
      });
    });
  });

for (const role of ROLES)
  test.describe(`C8 alerts centre R-190 and route sweep (tier A), ${role}`, () => {
    test.use({ charter: "C8", stubRole: role });

    test("alerts centre beside the shell states", async ({ page, ws, log }) => {
      await alertsCentre(page, log, role);
      const up = await live(page);
      log.note({
        step: "shell connection on the alerts centre",
        route: "/alerts",
        role,
        oracle: "none",
        result: up ? "info" : "suspect",
        note: `${up ? "live" : "still Reconnecting"}; ${ws.authenticated()} authenticated socket(s)`,
      });
    });

    test(`every route, socket stub on`, async ({ page, ws, log }) => {
      await stubAdminReads(page);
      let reconnecting = 0;
      for (const route of ROUTE_MANIFEST) {
        const path = concretePath(route.path);
        const r = await land(page, path);
        const badge = await page.getByRole("img", { name: BADGE }).count();
        const chromeless = ["/login", "/invite", "/offline", "/maintenance", "/404"].some((p) =>
          r.at.startsWith(p),
        );
        if (!chromeless && !(await live(page))) reconnecting += 1;
        log.note({
          step: `${route.id} ${path}`,
          route: r.at,
          role,
          oracle: "O8.1",
          result: badge > 0 || chromeless ? "ok" : "suspect",
          note: `h1 "${r.h1}", badge ${badge}`,
        });
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
      log.note({
        step: "shell connection across the sweep",
        route: "-",
        role,
        oracle: "none",
        result: reconnecting === 0 ? "info" : "suspect",
        note: `${reconnecting} shell route(s) still Reconnecting; ${ws.connections()} socket(s)`,
      });
    });
  });

test.describe("keyboard-only segment (03 §12), run 2 screens", () => {
  test.use({ charter: "KB", stubRole: "owner" });

  test("Tab sweep /login", async ({ page, log }) => {
    await page.route("**/api/v1/auth/refresh", (r) => r.fulfill(REFRESH_INVALID));
    await land(page, "/login");
    await tabSweep(page, 60, { log, route: "/login", role: "anonymous" });
  });

  const SCREENS = [
    "/settings/appearance",
    "/settings/hotkeys",
    "/settings/profile",
    "/admin",
    "/admin/users/new",
    "/alerts",
  ];
  for (const path of SCREENS)
    test(`Tab sweep ${path}`, async ({ page, ws, log }) => {
      await stubAdminReads(page);
      await land(page, path);
      await tabSweep(page, 200, { log, route: path, role: "owner" });
      log.note({
        step: "socket stub",
        route: path,
        role: "owner",
        oracle: "none",
        result: "info",
        note: `${ws.authenticated()} authenticated socket(s)`,
      });
    });
});

// ---------------------------------------------------------------- tier B, the seeded stack

/** Privileged calls, read-and-attempt: writes are made only as roles that must be refused. */
const PROBES: readonly Probe[] = [
  { method: "GET", path: "/api/v1/admin/overview", allow: ["owner"] },
  { method: "GET", path: "/api/v1/admin/capacity", allow: ["owner"] },
  { method: "GET", path: "/api/v1/admin/health", allow: ["owner"] },
  { method: "GET", path: "/api/v1/admin/feature-flags", allow: ["owner"] },
  { method: "GET", path: "/api/v1/admin/statecharts", allow: ["owner"] },
  { method: "GET", path: "/api/v1/admin/security/summary", allow: ["owner"] },
  // Manager scope for the audit read is not settled in the charters: noted, never judged, for Manager.
  { method: "GET", path: "/api/v1/admin/audit?limit=1", allow: ["owner", "manager"] },
  { method: "GET", path: "/api/v1/users", allow: ["owner"] },
  { method: "GET", path: "/api/v1/users/invites", allow: ["owner"] },
  {
    method: "POST",
    path: "/api/v1/users",
    body: {
      username: "fixture-invitee",
      email: "fixture-invitee@example.invalid",
      roles: ["viewer"],
      mfa_required: true,
    },
    allow: ["owner"],
  },
  { method: "PUT", path: "/api/v1/admin/feature-flags/explore-probe", body: {}, allow: ["owner"] },
  { method: "PUT", path: "/api/v1/admin/capacity/subaccount-tier", body: {}, allow: ["owner"] },
];

async function signedIn(page: Page, log: SessionLog, role: StubRole): Promise<void> {
  const s = await seededStack().signIn(page, role);
  log.note({
    step: "sign in on the seeded stack",
    route: "/login",
    role,
    oracle: "none",
    result:
      s.passwordStatus !== 200
        ? "suspect"
        : s.mfaStatus === 200 || s.mfaStatus === 0
          ? "info"
          : "suspect",
    note: `password status ${s.passwordStatus}, two-factor status ${s.mfaStatus}`,
  });
  await heading(page);
}

for (const role of ROLES)
  test.describe(`C7 server half (tier B), ${role}`, () => {
    test.use({ charter: "C7" });

    test("privileged calls with a real session", TIER_B, async ({ page, log }) => {
      await signedIn(page, log, role);
      const list = PROBES.filter((p) => p.method === "GET" || role !== "owner");
      const got = await callAs(page, list);
      if (got.statuses.length === 0)
        log.note({
          step: "cookie refresh",
          route: "-",
          role,
          oracle: "none",
          result: "suspect",
          note: `refresh ${got.refresh}: no session to probe with`,
        });
      list.forEach((p, i) => {
        const status = got.statuses[i];
        if (status === undefined) return;
        log.note({
          step: `${p.method} ${p.path}`,
          route: "-",
          role,
          oracle: "O7.2",
          result: judgeProbe(p, role, status),
          note: `status ${status}`,
        });
      });
    });

    test("admin overview, invite and alerts centre", TIER_B, async ({ page, log }) => {
      await signedIn(page, log, role);
      await adminPages(page, log, role);
      await alertsCentre(page, log, role);
    });
  });

test.describe("C7 two tabs, two roles (tier B)", () => {
  test.use({ charter: "C7" });

  test("Owner tab after a Viewer signs in on the second tab", TIER_B, async ({ page, log }) => {
    await signedIn(page, log, "owner");
    noteAdminLanding(log, "owner", await land(page, "/admin"));
    const second = await page.context().newPage();
    await signedIn(second, log, "viewer");
    // The first tab moves in the app, without a reload: what does it still show?
    await page.evaluate(() => {
      history.pushState({}, "", "/admin/users/new");
      dispatchEvent(new PopStateEvent("popstate"));
    });
    log.note({
      step: "first tab, in-app move after the second sign-in",
      route: "/admin/users/new",
      role: "owner tab, viewer cookie",
      oracle: "O7.4",
      result: "info",
      note: `h1 "${await heading(page)}"`,
    });
    const got = await callAs(page, PROBES.slice(0, 1));
    log.note({
      step: "first tab, privileged read on the shared cookie",
      route: "-",
      role: "owner tab, viewer cookie",
      oracle: "O7.4",
      result: got.statuses[0] === undefined ? "info" : got.statuses[0] < 300 ? "suspect" : "ok",
      note: `refresh ${got.refresh}, status ${got.statuses[0] ?? "none"}`,
    });
    const after = await land(page, "/admin");
    log.note({
      step: "first tab, reloaded",
      route: after.at,
      role: "owner tab, viewer cookie",
      oracle: "O7.4",
      result: DENIED.has(after.h1) ? "ok" : "suspect",
      note: `h1 "${after.h1}"`,
    });
    await second.close();
  });
});
