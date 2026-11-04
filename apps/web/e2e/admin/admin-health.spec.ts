import { test, expect, type Page } from "@playwright/test";
import { json, stubSession } from "../support/api";
import { seriousAxe } from "../support/axe";
import { HEALTH_OK, HEALTH_OUTAGE, PROTECTION_OK, stubOpsReads } from "../support/adminOps";
import { installWsHarness, type WsHarness } from "../support/wsHarness";

// E42-S06 (#1084) admin-health.spec: SCR-143 at /admin/health (E42-D05 §5), its reads answered at the
// network layer and its `system` frames from the fixture gateway (no backend, C-13.5): the UI halves of
// AD-S06-01 to -04, D9's two worlds, the detail view and both themes (HL-20).

type Replies = Parameters<typeof stubOpsReads>[1];
const tile = (page: Page, name: string) => page.getByRole("region", { name, exact: true });
const PRIVATE_WS = "Private WS (bybit_private_ws)";

async function openHealth(page: Page, replies: Replies = {}, theme?: "dark" | "light") {
  await stubSession(page, { role: "owner" });
  if (theme !== undefined) {
    await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({ appearance: { theme } })));
  }
  await stubOpsReads(page, replies);
  const harness: WsHarness = await installWsHarness(page);
  await page.goto("/admin/health");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("System health");
  await expect(page.locator('[data-cmp="CMP-178"][aria-busy="true"]')).toHaveCount(0);
  await expect.poll(() => harness.authenticated()).toBe(1);
  return harness;
}

/** A frame lists every probe (`23` §15.9): the report's components, the private stream degraded. */
const degrade = (harness: WsHarness): void =>
  harness.sendSystem({
    kind: "health",
    health: "degraded",
    components: (HEALTH_OK["components"] as { name: string }[]).map(({ name }) =>
      name === "bybit_private_ws"
        ? { name, state: "degraded", detail: "reconnecting" }
        : { name, state: "healthy" },
    ),
  });

test("E42-S06 AD-S06-01 each component is a region with its word and probe; one render measure", async ({
  page,
}) => {
  await openHealth(page);
  // A hard load leaves focus where the shell's route focus put it, never on Re-read.
  await expect(page.getByRole("button", { name: "Re-read" })).not.toBeFocused();
  await expect(page.getByRole("region", { name: "Admin area" })).toHaveText(
    "◆ Admin area · System health",
  );
  await expect(tile(page, "Postgres (postgres)")).toContainText("healthy");
  await expect(tile(page, "Postgres (postgres)")).toContainText("probe 3 ms");
  await expect(tile(page, "Disk (disk)")).not.toContainText("probe");
  await expect(tile(page, "Chart engine (this session)")).toContainText(
    "No chart open in this window",
  );
  await expect(page.getByText("fixture · fixture · demo · up 1 d 0 h")).toBeVisible();
  const measured = await page.evaluate(
    (name) => performance.getEntriesByName(name).length,
    "cv_admin_health_render_ms",
  );
  expect(measured).toBe(1);
});

for (const theme of ["dark", "light"] as const) {
  test(`E42-S06 SCR-143 has no serious axe violation in the ${theme} theme (HL-20)`, async ({
    page,
  }) => {
    await openHealth(page, {}, theme);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expect(await seriousAxe(page)).toEqual([]);
  });
}

test("E42-S06 AD-S06-03 a degraded frame escalates its own tile and names its impact; D9 withholds today", async ({
  page,
}) => {
  const harness = await openHealth(page);
  degrade(harness);
  const ws = tile(page, PRIVATE_WS);
  await expect(ws).toContainText("degraded — reconnecting");
  await expect(ws).toContainText("order and position updates may lag; REST reconcile runs.");
  await expect(ws).toContainText("Check the account's link on Exchange connectivity");
  await expect(ws).not.toContainText("Native stops on the exchange are unaffected.");
  await expect(tile(page, "Postgres (postgres)")).not.toContainText("degraded");
});

test("E42-S06 AD-S06-03 with every D9 leg holding, the degraded tile adds health.safe", async ({
  page,
}) => {
  const protection = { status: 200, body: PROTECTION_OK };
  const harness = await openHealth(page, {
    "/api/v1/admin/statecharts?kind=position_protection": protection,
  });
  degrade(harness);
  await expect(tile(page, PRIVATE_WS)).toContainText(
    "Native stops on the exchange are unaffected.",
  );
});

test("E42-S06 HL-5 the outage banner names what is down and does not speak", async ({ page }) => {
  await openHealth(page, { "/api/v1/admin/health": { status: 200, body: HEALTH_OUTAGE } });
  const banner = page.locator('[data-cmp="CMP-028"]');
  await expect(banner).toContainText("Down: Postgres, QuestDB. Each tile says what stops working.");
  await expect(banner).not.toContainText("Native stops"); // D9 withholds it today [BQ-9]
  await expect(banner.locator("[aria-live]")).toHaveCount(0);
  await expect(tile(page, "Postgres (postgres)")).toContainText("new orders are off");
});

test("E42-S06 AD-S06-04 a failed report keeps the numbers stale with Retry; the shell stays usable", async ({
  page,
}) => {
  const harness = await openHealth(page);
  await page.route("**/api/v1/admin/health", (r) => r.abort("timedout"));
  await page.getByRole("button", { name: "Re-read" }).click();
  // The main copy: the shell announcer says the same line once, politely.
  await expect(page.getByRole("main").getByText(/^Health report unavailable — /)).toBeVisible();
  const postgres = tile(page, "Postgres (postgres)");
  await expect(postgres).toContainText(/probe 3 ms.*stale since \d\d:\d\d:\d\d/u);
  degrade(harness);
  await expect(tile(page, PRIVATE_WS)).toContainText("degraded");
  const rail = page.getByRole("navigation", { name: "Primary" });
  await rail.getByRole("link", { name: "Journal", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/R-180/u);
});

test("E42-S06 AD-S06-02 the recorder's detail view lists its open incidents and links its screen", async ({
  page,
}) => {
  await openHealth(page);
  const heading = tile(page, "Recorder (recorder)").getByRole("link", {
    name: "Recorder (recorder)",
  });
  await heading.click();
  const back = page.getByRole("link", { name: "All components", exact: true });
  await expect(back).toBeFocused();
  await expect(
    page.getByText("error · recorder gap on BTCUSDT · last seen 2026-10-22 12:00 UTC"),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Recorder & storage" })).toHaveAttribute(
    "href",
    "/admin/recorder",
  );
  await expect(page.getByText("History isn't recorded yet.")).toBeVisible();
  await expect(page).toHaveTitle("System health - Recorder (recorder) - CandleViewer");
  await back.click();
  await expect(heading).toBeFocused();
  await expect(page).toHaveTitle("System health - CandleViewer");
});
