import { mkdirSync, writeFileSync } from "node:fs";
import { test } from "@playwright/test";
import { openScreen } from "./open";
import { REPORT_DIR, SCREENS, SIGNED_IN_SCREENS } from "./screens";

// Gate 6 collector: ARIA snapshot (role/name/landmark/heading tree) per screen
// as text -> reports/a11y/trees/<id>.txt. Signed-in screens are captured behind
// the /me stub (open.ts). Committed baselines live in tools/a11y/tree-snapshots/
// (refresh by copying the captured file in the PR).
test("collect a11y trees", async ({ page }) => {
  mkdirSync(`${REPORT_DIR}/trees`, { recursive: true });
  for (const s of [...SCREENS, ...SIGNED_IN_SCREENS]) {
    await openScreen(page, s);
    const tree = await page.locator("body").ariaSnapshot();
    writeFileSync(`${REPORT_DIR}/trees/${s.id}.txt`, `${tree}\n`);
  }
});
