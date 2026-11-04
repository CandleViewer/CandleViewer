// E12-Q03 (#419): what each e12-bars case waits for, in one place. No case is `test.fixme` (the #419
// BQ-1 ruling): the specs ride one Draft PR that turns ready only when a route mounts the chart
// panes and every case passes at merge. Each describe block carries its entry as a `blocked-by`
// annotation, so a red run names the missing surface.
export const MOUNT = "a route mounting the chart panes (E15-S02 #435, confirmed at its head)";

export const BLOCKED = {
  table: `${MOUNT}; SCR-045 as the panel's equal view (E11-S14 #521)`,
  probe: `${MOUNT}; the SCR-046 probe island v1, PROPOSED, if E11-T07 #523 merges as is`,
  seriesTypes: `${MOUNT}; CMP-222 on the toolbar and the ribbon kinds (E12-S07 #533)`,
  barModes: `${MOUNT}; SCR-041/SCR-042 bar-mode entry (CMP-220)`,
  states: `${MOUNT}; SCR-047/SCR-048 data-feed states on the panel`,
} as const;

/** The `details` of a describe block blocked on `entry`. */
export const blockedBy = (entry: string) =>
  ({ annotation: { type: "blocked-by", description: entry } }) as const;
