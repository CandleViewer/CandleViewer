// E15-S03 (#476) PR-1 (BQ-09: Q02's file names, extended later): the saved workspace restores in a
// real browser, through the REAL web client on the WS harness (the flag arrives as a `system` push,
// 23 §15.9) and the seeded workspace fixture (BQ-03). Saving joins in PR-2.
import { stubSession } from "../../support/api";
import { seriousAxe } from "../../support/axe";
import { installWsHarness } from "../../support/wsHarness";
import { WORKSPACE_DOCK_ON, seedWorkspace } from "../../support/workspace";
import { expect, test } from "../../shell/fixtures";

test("the seeded workspace restores through /terminal on the workspace route", async ({ page }) => {
  await stubSession(page, { role: "owner" });
  await installWsHarness(page, undefined, { firstAuthSystem: [WORKSPACE_DOCK_ON] });
  const path = await seedWorkspace(page);
  await page.goto("/terminal");
  await expect(page).toHaveURL(new RegExp(`${path}$`));
  await expect(page.getByRole("region", { name: /^Chart, BTCUSDT 1 minute, / })).toBeVisible();
  await expect(page.getByText("Workspace ready: Scalping, 1 panel.")).toBeAttached();
  expect(await seriousAxe(page)).toEqual([]);
});
