import { test, expect, type Page } from "@playwright/test";
import { json, stubSession } from "../support/api";
import { stubAdminReads } from "../support/admin";
import { seriousAxe } from "../support/axe";

// E42-S01 (#1022) admin-shell.spec: every admin route renders inside CMP-087 AdminLayout, whose code loads
// only once the route guard let the session in (BQ-7; E42-D03 §11: "the 404 with no call and no admin code
// loaded"). Per-action step-up (D8, BQ-1): no gate at the door. The API is stubbed at the network layer.

/** The admin area's lazy chunk: Vite names a dynamic import's chunk after its module, `AdminArea.tsx`. */
const ADMIN_CHUNK = /\/AdminArea-[^/]+\.js$/u;
const ADMIN_API = /^\/api\/v1\/admin(\/|$)/u;
const CHALLENGE_ID = "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d";
const SUMMARY = "Invite user 'annie' as viewer";

/** Every path the page asks for from now on: its scripts and its `/api/v1/` calls. */
function watchPaths(page: Page): () => string[] {
  const paths: string[] = [];
  page.on("request", (request) => paths.push(new URL(request.url()).pathname));
  return () => paths;
}

const band = (page: Page) => page.getByRole("region", { name: "Admin area" });

test("E42-S01 an owner enters the admin area: the band on each page, no gate and no step-up", async ({
  page,
}) => {
  const paths = watchPaths(page);
  await stubSession(page, { role: "owner" });
  await stubAdminReads(page); // the strip's reads on every admin route, SCR-120's at /admin
  const visit = async (path: string, label: string, h1: string): Promise<void> => {
    await page.goto(path);
    await expect(band(page)).toHaveText(`◆ Admin area · ${label}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(h1);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
  };
  await visit("/admin", "Overview", "Overview");
  await visit("/admin/users", "Users and roles", "R-301 — owned by E18");
  await visit("/admin/audit", "Audit log", "R-360 — owned by E09");
  await visit("/admin/security", "Security centre", "Security centre");
  await expect(page.getByText("Security posture checks ship in R4 (E43)")).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit log" })).toHaveAttribute(
    "href",
    "/admin/audit",
  );
  expect(await seriousAxe(page)).toEqual([]);
  expect(paths().filter((p) => p.endsWith("/auth/step-up"))).toEqual([]);
  expect(paths().some((p) => ADMIN_CHUNK.test(p))).toBe(true); // the watcher sees the chunk
  expect(paths()).toContain("/api/v1/admin/overview"); // and the owner's admin reads
});

test("E42-S01 focus moves to the page h1 when the admin area's code arrives", async ({ page }) => {
  await stubSession(page, { role: "owner" });
  await page.goto("/journal");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/R-180/u);
  const rail = page.getByRole("navigation", { name: "Primary" });
  await rail.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(band(page)).toHaveText("◆ Admin area · Overview");
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
});

for (const role of ["manager", "viewer"] as const) {
  test(`E42-S01 a ${role}'s admin route is the 404: no admin code loaded, no admin request`, async ({
    page,
  }) => {
    const paths = watchPaths(page);
    await stubSession(page, { role });
    await page.route(
      (url) => ADMIN_API.test(url.pathname),
      (r) => r.fulfill(json({ items: [] })),
    );
    for (const path of ["/admin", "/admin/users", "/admin/security"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
      await expect(band(page)).toHaveCount(0);
    }
    expect(paths()).toContain("/api/v1/me"); // positive control: the watcher sees the SPA's reads
    expect(paths().filter((p) => ADMIN_CHUNK.test(p))).toEqual([]);
    expect(paths().filter((p) => ADMIN_API.test(p))).toEqual([]);
  });
}

test("E42-S01 /admin/audit is framed for an owner only: a manager keeps the plain shell", async ({
  page,
}) => {
  const paths = watchPaths(page);
  await stubSession(page, { role: "manager" });
  await page.goto("/admin/audit");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("R-360 — owned by E09");
  await expect(band(page)).toHaveCount(0);
  expect(paths().filter((p) => ADMIN_CHUNK.test(p))).toEqual([]);
});

/** The owner on R-303 whose first invite the server refuses with a step-up challenge. */
async function challengedInvite(page: Page): Promise<{ creates: string[]; stepUps: string[] }> {
  const wire = { creates: [] as string[], stepUps: [] as string[] };
  await stubSession(page, { role: "owner" });
  await page.route("**/api/v1/users/invites", (r) => r.fulfill(json({ items: [] })));
  await page.route("**/api/v1/users", (r) => {
    wire.creates.push(r.request().headers()["idempotency-key"] ?? "");
    return wire.creates.length === 1
      ? r.fulfill(
          json(
            {
              type: "https://candleviewer.local/errors/step_up_required",
              title: "A dangerous action needs a live step-up elevation for its action class",
              status: 403,
              code: "step_up_required",
              action_class: "users",
              challenge_id: CHALLENGE_ID,
              challenge_expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
              action_summary: SUMMARY,
              target: null,
            },
            403,
          ),
        )
      : r.fulfill(
          json(
            {
              id: "u1",
              username: "annie",
              invite_url: "/invite/e2e-link",
              invite_expires_at: "2026-03-04T10:00:00Z",
            },
            201,
          ),
        );
  });
  await page.route("**/api/v1/auth/step-up", (r) => {
    wire.stepUps.push(r.request().postData() ?? "");
    return r.fulfill(json({ elevated_until: new Date().toISOString(), action_class: "users" }));
  });
  await page.goto("/admin/users/new");
  await expect(band(page)).toHaveText("◆ Admin area · Invite user");
  await page.getByLabel("Username").fill("annie");
  await page.getByLabel("Email").fill("annie@example.com");
  await page.getByRole("button", { name: "Create invitation" }).click();
  return wire;
}

test("E42-S01 (failure) a challenged invite inside the admin area: the page stays, re-sent once", async ({
  page,
}) => {
  const wire = await challengedInvite(page);
  const dialog = page.getByRole("alertdialog", { name: "Confirm with two-factor" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAccessibleDescription(SUMMARY);
  await expect(band(page)).toHaveCount(1);
  await expect(page.getByLabel("Username")).toHaveValue("annie"); // the form as the owner left it
  await expect(page.getByLabel("Email")).toHaveValue("annie@example.com");
  await page.getByLabel("Password", { exact: true }).fill("pw-admin-shell");
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByLabel("Invite link")).toHaveValue(/\/invite\/e2e-link$/u);
  expect(wire.stepUps.map((b) => JSON.parse(b) as unknown)).toEqual([
    { password: "pw-admin-shell", code: "123456", challenge_id: CHALLENGE_ID },
  ]);
  expect(wire.creates).toHaveLength(2);
  expect(wire.creates[1]).toBe(wire.creates[0]);
  await expect(band(page)).toHaveText("◆ Admin area · Invite user");
});
