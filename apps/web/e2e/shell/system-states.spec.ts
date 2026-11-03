import { stubSession } from "../support/api";
import { seriousAxe } from "../support/axe";
import { installWsHarness, type WsHarness } from "../support/wsHarness";
import { badge, expect, test } from "../ga/fixtures";

// E10-Q02 system states (plan step SS-1, SS-2) on E10-S04's surfaces, against the real web client
// with the API stubbed and the E08-Q05 WS harness as the gateway. Through every state the badge
// stays (the first E10 invariant). GPU unavailable is desktop-only (apps/desktop's
// e2e/system-states.spec.ts); forced panel/route crash are deferred rows in
// docs/qa/e10-shell-test-plan.md (no trigger a built app can reach, no apps/web/src seam: BQ-14).

async function signedIn(page: Parameters<typeof stubSession>[0]): Promise<WsHarness> {
  await stubSession(page, { role: "manager" });
  const harness = await installWsHarness(page);
  await page.goto("/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);
  await expect(page.getByRole("banner").getByText("Live", { exact: true })).toBeVisible();
  return harness;
}

test("@plan-SS-1 WS dropped: the top bar says Reconnecting, then Live again after the restore @ga-regression @ga-area-shell", async ({
  page,
}) => {
  const harness = await signedIn(page);
  harness.kill();
  await expect(page.getByRole("banner").getByText("Reconnecting")).toBeVisible();
  await expect(badge(page)).toBeVisible();
  expect(await seriousAxe(page)).toEqual([]);
  harness.restore();
  await expect.poll(() => harness.authenticated(), { timeout: 15_000 }).toBe(2);
  await expect(page.getByRole("banner").getByText("Live", { exact: true })).toBeVisible();
  await expect(badge(page)).toBeVisible();
});

test("@plan-SS-2 backend killed mid-session: SCR-159's offline page takes over, the badge stays @ga-regression @ga-area-shell", async ({
  page,
}) => {
  const harness = await signedIn(page);
  // the backend process dies: every API call is refused and the gateway drops the socket
  await page.route("**/api/v1/**", (r) => r.abort("connectionrefused"));
  harness.kill();
  await expect(
    page.getByRole("heading", { level: 1, name: "Not connected to the tailnet" }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(badge(page)).toBeVisible();
  expect(await seriousAxe(page)).toEqual([]);
});
