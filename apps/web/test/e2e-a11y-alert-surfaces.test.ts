// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  ALERT_SURFACE_ENTRIES,
  ALERT_SURFACES,
  ALERT_THEMES,
  ALERT_ZOOMS,
  skippedAlertEntries,
} from "../e2e/a11y/alert-surfaces";
import { SCREENS, SIGNED_IN_SCREENS } from "../e2e/a11y/screens";

describe("E40 alert-surface a11y matrix (E40-Q02 pre-stage)", () => {
  it("covers the five surfaces x 3 themes x 2 zooms with unique ids", () => {
    expect(ALERT_SURFACES).toHaveLength(5);
    expect(ALERT_SURFACE_ENTRIES).toHaveLength(5 * ALERT_THEMES.length * ALERT_ZOOMS.length);
    expect(new Set(ALERT_SURFACE_ENTRIES.map((e) => e.id)).size).toBe(ALERT_SURFACE_ENTRIES.length);
  });

  it("names a blocker on every entry and reports each as skipped", () => {
    for (const e of ALERT_SURFACE_ENTRIES) expect(e.blockedBy).toMatch(/E40-S0[12] #\d+/);
    const skipped = skippedAlertEntries();
    expect(skipped).toHaveLength(ALERT_SURFACE_ENTRIES.length);
    expect(skipped.every((s) => s.reason.startsWith("skipped: blocked by E40-S"))).toBe(true);
  });

  it("is not part of the collected screen sets until an entry is un-skipped", () => {
    const collected = new Set([...SCREENS, ...SIGNED_IN_SCREENS].map((s) => s.id));
    for (const e of ALERT_SURFACE_ENTRIES) expect(collected.has(e.id)).toBe(false);
  });
});
