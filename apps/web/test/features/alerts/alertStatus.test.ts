import { describe, expect, it } from "vitest";
import {
  deriveAlertStatus,
  filterAlerts,
  matchesTab,
  tabCounts,
} from "../../../src/features/alerts/alertStatus.js";
import type { Alert } from "../../../src/features/alerts/types.js";

const NOW = Date.parse("2026-10-31T12:00:00Z");
const base = (over: Partial<Alert>): Alert => ({ id: "a", enabled: true, ...over }) as Alert;

describe("deriveAlertStatus", () => {
  it("is armed when enabled and never fired", () => {
    expect(deriveAlertStatus(base({}), NOW)).toBe("armed");
  });
  it("is fired once last_fired_at is set", () => {
    expect(deriveAlertStatus(base({ last_fired_at: "2026-10-31T11:00:00Z" }), NOW)).toBe("fired");
  });
  it("is fired from fire_count alone", () => {
    expect(deriveAlertStatus(base({ fire_count: 2 }), NOW)).toBe("fired");
  });
  it("is snoozed while snoozed_until is in the future, and wins over fired", () => {
    const alert = base({ snoozed_until: "2026-10-31T12:00:01Z", fire_count: 1 });
    expect(deriveAlertStatus(alert, NOW)).toBe("snoozed");
  });
  it("ignores an elapsed, equal, null or unparseable snooze", () => {
    expect(deriveAlertStatus(base({ snoozed_until: "2026-10-31T12:00:00Z" }), NOW)).toBe("armed");
    expect(deriveAlertStatus(base({ snoozed_until: null }), NOW)).toBe("armed");
    expect(deriveAlertStatus(base({ snoozed_until: "nope" }), NOW)).toBe("armed");
  });
  it("is disarmed whenever enabled is false, over snooze and fired", () => {
    const alert = base({ enabled: false, snoozed_until: "2026-11-01T00:00:00Z", fire_count: 3 });
    expect(deriveAlertStatus(alert, NOW)).toBe("disarmed");
    expect(
      deriveAlertStatus(base({ enabled: false, disarm_reason: "source_unavailable" }), NOW),
    ).toBe("disarmed");
  });
});

describe("tabs", () => {
  const alerts = [
    base({ id: "1" }),
    base({ id: "2", fire_count: 1 }),
    base({ id: "3", snoozed_until: "2026-11-01T00:00:00Z" }),
    base({ id: "4", enabled: false }),
  ];
  it("matchesTab: all matches everything, others match their status", () => {
    expect(matchesTab("disarmed", "all")).toBe(true);
    expect(matchesTab("fired", "fired")).toBe(true);
    expect(matchesTab("fired", "snoozed")).toBe(false);
  });
  it("filters All, Fired and Snoozed", () => {
    expect(filterAlerts(alerts, "all", NOW)).toBe(alerts);
    expect(filterAlerts(alerts, "fired", NOW).map((a) => a.id)).toEqual(["2"]);
    expect(filterAlerts(alerts, "snoozed", NOW).map((a) => a.id)).toEqual(["3"]);
  });
  it("counts per tab", () => {
    expect(tabCounts(alerts, NOW)).toEqual({ all: 4, fired: 1, snoozed: 1 });
  });
});
