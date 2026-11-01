import { test, expect, type Page } from "@playwright/test";
import { json, stubSession } from "../support/api";
import { ADMIN_OVERVIEW, stubAdminReads } from "../support/admin";
import { seriousAxe } from "../support/axe";

// E42-S01 (#1022) admin-overview.spec: SCR-120 at /admin (E42-D03 §6), its reads answered at the network
// layer (no backend, C-13.5). The amended Gherkin's AC3 (tiles resolve independently, the render measured
// once; its 800 ms budget is E42-Q03's), AC5 (a degraded backend: last-known values stale, Retry, the shell
// usable) and the 403 that withdraws the area.

const RENDER_MEASURE = "cv_admin_overview_render_ms";
const tile = (page: Page, name: string | RegExp) => page.getByRole("region", { name });

/** The owner on /admin with every tile answered, in `theme` when one is given. */
async function openOverview(
  page: Page,
  theme?: "dark" | "light",
): Promise<(path: string, status: number, body: unknown) => void> {
  await stubSession(page, { role: "owner" });
  // A route registered later wins: this one answers the shell's preferences read instead.
  if (theme !== undefined) {
    await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({ appearance: { theme } })));
  }
  const set = await stubAdminReads(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Overview");
  await expect(page.locator('[data-cmp="CMP-178"][aria-busy="true"]')).toHaveCount(0);
  return set;
}

test("E42-S01 AC3 the tiles resolve on their own: the recorder errs, the rest read; one render measure", async ({
  page,
}) => {
  await openOverview(page);
  await expect(page.getByRole("region", { name: "Admin area" })).toHaveText(
    "◆ Admin area · Overview",
  );
  await expect(page.getByRole("heading", { level: 2 })).toHaveText([
    "Right now",
    "People and access",
    "Evidence and controls",
  ]);
  await expect(page.locator('[data-cmp="CMP-178"]')).toHaveCount(9);
  const recorder = tile(page, "Recorder and storage");
  await expect(recorder).toContainText("Error — timed out after 300 ms");
  await expect(recorder.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(tile(page, "Users")).toContainText("as of 12:00:00");
  await expect(tile(page, /^Trading safety/)).toContainText("Kill switch");
  await expect(tile(page, "Health")).toContainText("1 component not deployed");
  await expect(tile(page, "Profiles and limits")).toContainText("Unavailable — not built yet");
  await expect(tile(page, "Security and backups")).toContainText(
    "Last backupUnavailable — not built yet",
  );
  // The strip's one served item, and the footer that the entry was recorded.
  const strip = page.getByRole("region", { name: "Needs your action" });
  await expect(strip.getByRole("link")).toHaveAccessibleName(
    "Attention: Tier not recorded → Record tier",
  );
  await expect(
    page.getByText("Entering this area was recorded — Area entered (admin.area_entered)"),
  ).toBeVisible();
  // The page measures its render once, when every tile has answered. The 800 ms budget (`14` SCR-120)
  // is E42-Q03's, on its own runner: a shared one times load, not the page (C-5330-09).
  const measured = await page.evaluate(
    (name) => performance.getEntriesByName(name).map((e) => e.duration),
    RENDER_MEASURE,
  );
  expect(measured).toHaveLength(1);
  expect(Number.isFinite(measured[0])).toBe(true);
});

for (const theme of ["dark", "light"] as const) {
  test(`E42-S01 the overview has no serious axe violation in the ${theme} theme`, async ({
    page,
  }) => {
    await openOverview(page, theme);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expect(await seriousAxe(page)).toEqual([]);
  });
}

test("E42-S01 AC5 a 503 keeps the last-known values marked stale with Retry; the shell stays usable", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-22T12:00:05Z") });
  const set = await openOverview(page);
  await expect(tile(page, "Users")).toContainText("Total9");
  set("/api/v1/admin/overview", 503, { status: 503, code: "audit_unavailable" });
  await page.clock.fastForward(30_000);
  const users = tile(page, "Users");
  await expect(users).toContainText(/stale since 12:00:\d\d/u);
  await expect(users).toContainText("Total9");
  await expect(users.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(tile(page, /^Trading safety/)).toContainText("Kill switchunknown");
  // A Retry that is answered clears the mark.
  set("/api/v1/admin/overview", 200, ADMIN_OVERVIEW);
  await users.getByRole("button", { name: "Retry" }).click();
  await expect(users).toContainText("as of 12:00:00");
  // The shell's navigation works throughout.
  const rail = page.getByRole("navigation", { name: "Primary" });
  await rail.getByRole("link", { name: "Journal", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/R-180/u);
});

test("E42-S01 a 403 on an admin read withdraws the area: 'Your access changed', no band", async ({
  page,
}) => {
  await stubSession(page, { role: "owner" });
  await stubAdminReads(page, {
    "/api/v1/admin/health": {
      status: 403,
      body: { code: "forbidden", instance: "urn:cv:req:5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f" },
    },
  });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your access changed");
  await expect(page.getByRole("region", { name: "Admin area" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Back to your workspace" })).toHaveAttribute(
    "href",
    "/terminal",
  );
  await expect(page.getByText("Ref urn:cv:req:5b1f0c3e-7d2a-4c11-9e8f-0a1b2c3d4e5f")).toBeVisible();
});
