import { test } from "@playwright/test";

// E49-Q01 (#1335, BQ-01/BQ-03): the pack's carried Electron-only flows, as apps/web's
// e2e/ga/carried.spec.ts: `test.fixme` stubs that cover nothing until their surface ships, each a
// declared gap in docs/qa/ga-coverage-gaps.json, owned by the epic in its title (a person is
// assigned when that epic's ticket is claimed). When one ships, its body launches through
// e2e/support/shell.ts (the Electron egress guard), which tools/ga/health.py then requires.
// GPU-unavailable fallback is already in the pack (system-states.spec.ts).

test.fixme("@plan-GA-CARRIED floating windows (E15) @ga-regression @ga-area-shell @story-US-LAY-005", () => {});
test.fixme("@plan-GA-CARRIED auto-update prompt, staging channel only (E10, E48) @ga-regression @ga-area-shell", () => {});
