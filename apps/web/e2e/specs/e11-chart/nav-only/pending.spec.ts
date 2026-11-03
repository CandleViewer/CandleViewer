// E11-Q02 (#444, AC1). Keyboard rows whose surface is not on main: each is a fixme naming its owner,
// flipped when the owner lands. E11-S13 (#5480) is a blocker of the closing PR, which leaves no fixme.
// The pointer guard (support/engine/nav-guard.ts) applies to all of them.
import { test } from "../../../support/engine/nav-guard";

test.describe("keyboard rows pending E11-S13 (#5480) @candidate", () => {
  test.fixme("Tab from the page start reaches the chart (C04 step 1)", async () => {
    // pending #5480: the chart's plot Tab stop is E11-S13's; today the figure is tabindex -1.
  });
  test.fixme("arrows step the data cursor and the readout follows (C11, C40)", async () => {
    // pending #5480: the data cursor (E11-S13).
  });
  test.fixme("Alt+T opens the data table and focus returns on close (C04)", async () => {
    // pending #5480: the Alt+T table (E11-S13).
  });
});
