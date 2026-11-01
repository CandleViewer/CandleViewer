import { json, sessionInfo, stubSession } from "../support/api";
import { seriousAxe } from "../support/axe";
import { badge, expect, test } from "../ga/fixtures";

// E10-Q02, the per-PR abuse subset absorbed from E10-X03 (plan step AB-1..AB-4). Each title names
// the client-side control it holds; the server-side half (C-12.4) is the backend RBAC suite.

const ADMIN_PATHS = ["/admin", "/admin/users", "/admin/keys/x1/rotate"];

for (const role of ["manager", "viewer"] as const)
  test(`@abuse @plan-AB-1 route guard: a ${role}'s admin deep links render not-found and fetch no admin data @ga-regression @ga-area-admin`, async ({
    page,
  }) => {
    const adminCalls: string[] = [];
    await stubSession(page, { role });
    await page.route("**/api/v1/admin/**", (r) => {
      adminCalls.push(new URL(r.request().url()).pathname);
      return r.fulfill(json({ items: [] }));
    });
    for (const path of ADMIN_PATHS) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
      await expect(badge(page)).toBeVisible();
    }
    expect(adminCalls).toEqual([]);
  });

test("@abuse @plan-AB-2 route guard: after a server-side downgrade the next navigation re-reads /me and denies the admin route @ga-regression @ga-area-admin", async ({
  page,
}) => {
  let role: "owner" | "viewer" = "owner";
  let meReads = 0;
  await stubSession(page, { role: "owner" });
  // registered after stubSession, so these answer first (Playwright runs the newest route first)
  await page.route("**/api/v1/me", (r) => {
    meReads += 1;
    return r.fulfill(
      json({ role, permissions: [], session: { environment: "demo", elevated_until: null } }),
    );
  });
  await page.route(
    (url) => url.pathname === "/api/v1/auth/session",
    (r) => r.fulfill(json(sessionInfo(role))),
  );
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { level: 1, name: /^R-301/u })).toBeVisible();
  const before = meReads;
  role = "viewer"; // the server downgrades the user
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  expect(meReads).toBeGreaterThan(before);
});

// Preference values a hostile or corrupt server row could carry: CSS-like text and extreme scales.
const HOSTILE_APPEARANCE = [
  { theme: "dark}[role=img]{display:none", density: "compact" },
  { theme: "light", density: "comfortable;visibility:hidden", font_scale: 0.01 },
  { theme: "dark", high_contrast: true, font_scale: 40 },
];

for (const [n, appearance] of HOSTILE_APPEARANCE.entries())
  test(`@abuse @plan-AB-3 badge: preference set ${n + 1} cannot hide the environment badge @ga-regression @ga-area-admin`, async ({
    page,
  }) => {
    await stubSession(page, { role: "viewer" });
    await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({ appearance })));
    await page.goto("/terminal");
    await expect(badge(page)).toBeVisible();
    await expect(badge(page)).toBeInViewport();
  });

test("@abuse @plan-AB-3 badge: at 200% zoom (half the CSS viewport) the badge stays in view @ga-regression @ga-area-admin", async ({
  page,
}) => {
  await page.setViewportSize({ width: 640, height: 400 }); // 1280x800 at 200%
  await stubSession(page, { role: "viewer" });
  await page.goto("/terminal");
  await expect(badge(page)).toBeInViewport();
  expect(await seriousAxe(page)).toEqual([]);
});

test("@abuse @plan-AB-4 CSP: a stylesheet from another origin is refused (style-src 'self') @ga-regression @ga-area-admin", async ({
  page,
}) => {
  await stubSession(page, { role: "viewer" });
  await page.goto("/terminal");
  await expect(badge(page)).toBeVisible();
  const violation = await page.evaluate(
    () =>
      new Promise<string>((resolve) => {
        const doc = (globalThis as unknown as { document: Document }).document;
        doc.addEventListener("securitypolicyviolation", (e) => resolve(e.effectiveDirective), {
          once: true,
        });
        const link = doc.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://styles.invalid/hide-badge.css";
        doc.head.append(link);
      }),
  );
  expect(violation).toBe("style-src-elem");
  await expect(badge(page)).toBeVisible();
});
