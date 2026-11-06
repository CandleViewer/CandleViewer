/**
 * E42-S06 (#1084) part 1: D9's gate (ruling Q11): every leg passing shows `health.safe`, each leg
 * alone withholds it, and today's `unavailable` snapshots withhold it everywhere [BQ-9].
 */
import { describe, expect, it } from "vitest";
import { stillSafe, type GateLegs } from "../../../../src/features/admin/health/gate";
import type { IncidentPageBody, Incident } from "../../../../src/features/admin/ops/opsReads";

const page = (items: Partial<Incident>[] = [], has_more = false): IncidentPageBody => ({
  items: items.map((over) => ({
    id: "i1",
    component: "recorder",
    severity: "error",
    status: "open",
    first_seen_at: "2026-10-22T14:00:00Z",
    last_seen_at: "2026-10-22T14:00:00Z",
    ...over,
  })),
  meta: { has_more, count: items.length, next_cursor: has_more ? "c" : null },
});
const ALL_PASS: GateLegs = {
  oms: { state: "healthy", fresh: true },
  open: page([{ component: "recorder" }]),
  acknowledged: page(),
  protection: {
    kinds: [
      { machine_kind: "position_protection", degraded_machines: 0 },
      { machine_kind: "order", degraded_machines: 3 },
    ],
    snapshots: { status: "ok" },
  },
};
const safe = (over: Partial<GateLegs>, component = "bybit_rest"): boolean =>
  stillSafe(component, { ...ALL_PASS, ...over });

describe("D9's gate", () => {
  it("test_gate_every_leg_passing_shows_the_sentence", () => {
    expect(safe({})).toBe(true);
    expect(safe({ oms: { state: "not_deployed", fresh: true } })).toBe(true);
  });

  it.each(["degraded", "warning", "down"] as const)("test_gate_oms_%s_withholds_it", (state) => {
    expect(safe({ oms: { state, fresh: true } })).toBe(false);
  });

  it("test_gate_oms_stale_or_not_received_withholds_it_and_its_own_tile_never_says_it", () => {
    expect(safe({ oms: { state: "healthy", fresh: false } })).toBe(false);
    expect(safe({ oms: undefined })).toBe(false);
    expect(safe({}, "oms")).toBe(false);
  });

  it("test_gate_an_oms_incident_on_either_page_withholds_it", () => {
    expect(safe({ open: page([{ component: "oms" }]) })).toBe(false);
    expect(safe({ acknowledged: page([{ component: "oms", status: "acknowledged" }]) })).toBe(
      false,
    );
  });

  it("test_gate_a_page_with_more_to_read_withholds_it", () => {
    expect(safe({ open: page([{ component: "recorder" }], true) })).toBe(false);
    expect(safe({ acknowledged: page([], true) })).toBe(false);
  });

  it("test_gate_a_pending_or_failed_incident_read_withholds_it", () => {
    expect(safe({ open: undefined })).toBe(false);
    expect(safe({ acknowledged: undefined })).toBe(false);
  });

  it("test_gate_protection_pending_latched_or_its_snapshots_not_ok_withholds_it", () => {
    const latched = { machine_kind: "position_protection", degraded_machines: 1 };
    expect(safe({ protection: undefined })).toBe(false);
    expect(safe({ protection: { kinds: [latched], snapshots: { status: "ok" } } })).toBe(false);
    // No `position_protection` row cannot show that none is latched.
    const order = { machine_kind: "order", degraded_machines: 0 };
    for (const kinds of [[], [order]]) {
      expect(safe({ protection: { kinds, snapshots: { status: "ok" } } })).toBe(false);
    }
    for (const status of ["unavailable", "error"] as const) {
      expect(safe({ protection: { kinds: [], snapshots: { status } } })).toBe(false);
    }
  });

  it.each(["unavailable", "error"] as const)(
    "test_gate_snapshots_%s_alone_withholds_it_with_every_other_leg_passing",
    (status) => {
      const kinds = ALL_PASS.protection?.kinds ?? [];
      expect(safe({ protection: { kinds, snapshots: { status: "ok" } } })).toBe(true);
      expect(safe({ protection: { kinds, snapshots: { status } } })).toBe(false);
    },
  );

  it("test_gate_one_latched_slice_among_several_withholds_it", () => {
    const slice = (degraded_machines: number) => ({
      machine_kind: "position_protection",
      degraded_machines,
    });
    const snapshots = { status: "ok" } as const;
    expect(safe({ protection: { kinds: [slice(0), slice(0), slice(0)], snapshots } })).toBe(true);
    for (const kinds of [
      [slice(1), slice(0), slice(0)],
      [slice(0), slice(0), slice(2)],
    ]) {
      expect(safe({ protection: { kinds, snapshots } })).toBe(false);
    }
  });
});
