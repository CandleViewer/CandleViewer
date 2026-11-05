/**
 * C-6.2 consumer contract (E42-S08, #1137): the inspector reads `listStatecharts`, `getStatechart` and
 * `exportStatechart` (`22`, E42-T07) through the generated `packages/protocol` types, never a hand-written
 * DTO (C-4.16), and `22`'s three examples land where E42-D05 §11 draws them: `degradedOrder` on SI-1 (the
 * latched order's row, a counters-only kind, the metrics slice's failure, no dropped receipts count), and
 * `killSwitch`'s detail and export on SI-4 (the configuration's leaf marked current, read from the
 * configuration alone). The examples are the test fixtures, each citing its `22` lines; their machine hashes
 * are the committed `machine_hashes.lock`'s, read when the tests run, so a chart bump moves no web test (the
 * web tests read no YAML, and `22`'s examples keep whatever hashes their owners give them).
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import { currentIds } from "../../src/features/admin/statecharts/chartModel";
import {
  vetDetail,
  vetExport,
  vetList,
  type AdminSliceStatus,
  type MachineDetail,
  type MachineList,
  type StatechartExport,
  type StatechartKindSummary,
  type StatechartMachine,
} from "../../src/features/admin/statecharts/inspectorReads";
import { isRowless } from "../../src/features/admin/statecharts/kinds";
import { vetMachineState } from "../../src/features/admin/statecharts/machineFeed";
import {
  DEGRADED_ORDER_LIST,
  KILL_SWITCH_DETAIL,
  KILL_SWITCH_EXPORT,
  KILL_SWITCH_HASH,
  ORDER_HASH,
} from "../features/admin/statecharts/fixtures";

type Schemas = generated.rest.components["schemas"];
type Ops = generated.rest.operations;
type Ok<K extends keyof Ops> = Ops[K] extends {
  responses: { 200: { content: { "application/json": infer B } } };
}
  ? B
  : never;

describe("statechart inspector consumer contract (C-6.2)", () => {
  it("test_contract_inspector_types_are_the_generated_ones", () => {
    expectTypeOf<StatechartMachine>().toEqualTypeOf<Schemas["StatechartMachine"]>();
    expectTypeOf<StatechartKindSummary>().toEqualTypeOf<Schemas["StatechartKindSummary"]>();
    expectTypeOf<StatechartExport>().toEqualTypeOf<Schemas["StatechartExport"]>();
    expectTypeOf<AdminSliceStatus>().toEqualTypeOf<Schemas["AdminSliceStatus"]>();
    expectTypeOf<MachineList["meta"]>().toEqualTypeOf<Ok<"listStatecharts">["meta"]>();
    // The detail keeps every field it shows; `config` and `context_summary` are never kept (BQ-4).
    expectTypeOf<MachineDetail>().toEqualTypeOf<
      Omit<Ok<"getStatechart">, "config" | "context_summary">
    >();
  });

  it("test_contract_a_machines_topic_payload_of_the_schema_is_read", () => {
    // `23` §15.10 as generated: a payload the schema allows is one the live feed reads (BQ-7).
    const payload: generated.ws.MachinesEntityState = {
      machine_kind: "kill_switch",
      state: "clear",
      tags: [],
      degraded: false,
      machine_hash: KILL_SWITCH_HASH,
      environment: "demo",
      updated_at_ms: Date.parse("2026-10-15T18:00:00Z"),
      context_summary: { scope: "global", cancel_working: true, flatten: false },
    };
    expect(vetMachineState(payload, { key: "kill_switch", env: "demo" })).toEqual({
      state: "clear",
      regions: {},
      degraded: false,
      at: payload.updated_at_ms,
    });
  });

  it("test_contract_degraded_order_lands_on_si1", () => {
    const list = vetList(DEGRADED_ORDER_LIST);
    expect(list).not.toBeNull();
    // Every row and counter the server sends is read: none is dropped as unknown.
    expect(list?.items).toHaveLength(DEGRADED_ORDER_LIST.items.length);
    expect(list?.kinds).toHaveLength(DEGRADED_ORDER_LIST.kinds.length);
    const latched = list?.items.filter((row) => row.degraded) ?? [];
    expect(latched.map((row) => [row.machine_kind, row.chain_trips, row.deferred_depth])).toEqual([
      ["order", 1, 2],
    ]);
    // A kind with no public id is counted, never listed (`22`: B8, B9, B13 and B15 get no row).
    const rowless = list?.kinds.filter((k) => isRowless(k.machine_kind)) ?? [];
    expect(rowless.map((k) => k.machine_kind)).toEqual(["position_protection"]);
    expect(list?.items.some((row) => isRowless(row.machine_kind))).toBe(false);
    // The metrics source failed: its slice says why, and no dropped receipts count is given.
    expect(list?.metrics).toEqual(DEGRADED_ORDER_LIST.metrics);
    expect(list?.kinds.every((k) => k.dropped_receipts === null)).toBe(true);
  });

  it("test_contract_kill_switch_detail_and_export_land_on_si4", () => {
    const detail = vetDetail(KILL_SWITCH_DETAIL);
    const exported = vetExport(KILL_SWITCH_EXPORT, "kill_switch");
    if (detail === null || exported === null) throw new Error("22's killSwitch examples refused");
    expect(detail).not.toHaveProperty("config");
    expect(detail).not.toHaveProperty("context_summary");
    // The highlight's guard: the export's hash is the machine's (MUST-12).
    expect(exported.machine_hash).toBe(detail.machine?.machine_hash);
    expect([...currentIds(exported.model, detail.configuration ?? [])]).toEqual([
      "kill_switch.clear",
    ]);
  });

  it("test_contract_fixture_hashes_meet_the_machine_hash_pattern", () => {
    // Read from the committed lock when the tests run (`fixtures.ts`): each is a sha256, the
    // pattern `22` gives `StatechartMachine.machine_hash` and `StatechartExport.machine_hash`.
    for (const [kind, hash] of [
      ["order", ORDER_HASH],
      ["kill_switch", KILL_SWITCH_HASH],
    ] as const) {
      expect(hash, kind).toMatch(/^[0-9a-f]{64}$/);
    }
  });
});
