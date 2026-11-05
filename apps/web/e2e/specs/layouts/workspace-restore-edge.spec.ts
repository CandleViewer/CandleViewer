// E15-S03 (#476) PR-1 (BQ-09: Q02's file names, extended later): a delisted symbol on restore, in a
// real browser, through the REAL web client on the WS harness and the seeded workspace (BQ-03).
import { stubSession } from "../../support/api";
import { seriousAxe } from "../../support/axe";
import { installWsHarness } from "../../support/wsHarness";
import { WORKSPACE_DOCK_ON, seedWorkspace } from "../../support/workspace";
import { expect, test } from "../../shell/fixtures";

test("a delisted symbol degrades one pane only; the others load", async ({ page }) => {
  await stubSession(page, { role: "owner" });
  await installWsHarness(page, undefined, { firstAuthSystem: [WORKSPACE_DOCK_ON] });
  await seedWorkspace(page, [
    ["chart", "BTCUSDT", "time:1"],
    ["chart", "ETHUSDT", "time:15"],
    ["dom", "SOLUSDT"],
    ["chart", "LUNAUSDT", "time:5"],
  ]);
  await page.goto("/terminal");
  const delisted = page.getByRole("region", { name: /^Chart, LUNAUSDT/ });
  await expect(
    delisted.getByText("LUNAUSDT is no longer listed. This panel can't load it."),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: /^DOM, SOLUSDT, / })).toBeVisible();
  await expect(page.getByText(/no longer listed/)).toHaveCount(1);
  const ready = /^Workspace ready: 3 of 4 panels\. 1 panel couldn't load: Chart, LUNAUSDT/;
  await expect(page.getByText(ready)).toBeAttached();
  expect(await seriousAxe(page)).toEqual([]);
  // FM-11 by keyboard: Enter on "Close panel" hands focus to the panel that takes the space.
  await delisted.getByRole("button", { name: "Close panel" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: /^DOM, SOLUSDT, / })).toBeFocused();
});
