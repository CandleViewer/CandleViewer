// E12-Q03 (#419): why each e12-bars case is `test.fixme` on `main`. The required Playwright check
// runs every spec in this directory, so a case un-fixmes only in the PR that makes it pass on
// `main` (the #772 BQ-1 rule). No route mounts a chart panel yet: that is the first blocker of all.
export const MOUNT = "a route mounting a chart panel (E15-S02 #435 on E15-S01 #401's route)";

export const BLOCKED = {
  table: `${MOUNT}; SCR-045 as the panel's equal view (E11-S14 #521)`,
  probe: `${MOUNT}; the SCR-046 diagnostics island (E11-T07 #523)`,
  seriesTypes: `${MOUNT}; CMP-222 on the toolbar and the ribbon kinds (E12-S07 #533, PR #5593)`,
  barModes: `${MOUNT}; SCR-041/SCR-042 bar-mode entry (CMP-220)`,
  forming: `${MOUNT}; a bars-topic sender in the WS fixture gateway (23 §6.1)`,
  states: `${MOUNT}; SCR-047/SCR-048 data-feed states on the panel`,
} as const;
