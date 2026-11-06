/**
 * C-6.2 consumer contract (E42-S06, #1084 part 1): SCR-143 reads the health bodies the server's own
 * tests pin (`services/api/tests/fixtures/admin/payloads`) through the generated `packages/protocol`
 * types, and each lands on the records E42-D05 §5.3 draws for it. Every alias the ops reads use is
 * the generated type (C-4.16).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  mergeComponents,
  NO_WORDS,
  type SystemUpdate,
} from "../../src/features/admin/health/frames";
import {
  vetHealthReport,
  type ComponentState,
  type HealthReport,
  type Incident,
  type IncidentPageBody,
  type ProtectionBody,
} from "../../src/features/admin/ops/opsReads";

type Schemas = generated.rest.components["schemas"];

const PAYLOADS = resolve(
  import.meta.dirname,
  "../../../../services/api/tests/fixtures/admin/payloads",
);
const payload = (name: string): unknown =>
  JSON.parse(readFileSync(resolve(PAYLOADS, `${name}.json`), "utf8")) as unknown;

describe("admin ops consumer contract (C-6.2)", () => {
  it("test_contract_ops_types_are_the_generated_ones", () => {
    expectTypeOf<HealthReport>().toEqualTypeOf<Schemas["HealthReport"]>();
    expectTypeOf<ComponentState>().toEqualTypeOf<Schemas["ComponentState"]>();
    expectTypeOf<IncidentPageBody["items"][number]>().toEqualTypeOf<Incident>();
    expectTypeOf<Incident>().toEqualTypeOf<Schemas["Incident"]>();
    expectTypeOf<IncidentPageBody["meta"]>().toEqualTypeOf<Schemas["PageMeta"]>();
    expectTypeOf<ProtectionBody["kinds"][number]>().toEqualTypeOf<
      Pick<Schemas["StatechartKindSummary"], "machine_kind" | "degraded_machines">
    >();
    expectTypeOf<ProtectionBody["snapshots"]>().toEqualTypeOf<
      Pick<Schemas["AdminSliceStatus"], "status">
    >();
    expectTypeOf<SystemUpdate>().toEqualTypeOf<generated.ws.System>();
  });

  it("test_contract_health_degraded_reads_the_private_stream_degraded_alone", () => {
    const body = vetHealthReport(payload("health_degraded"));
    expect(body).not.toBeNull();
    const records = mergeComponents(
      body === null ? undefined : { body, at: 0 },
      NO_WORDS,
      undefined,
    );
    expect(records).toHaveLength(10);
    expect(records.filter((r) => r.state !== "healthy")).toEqual([
      {
        name: "bybit_private_ws",
        source: "report",
        state: "degraded",
        detail: "fixture: the private stream for sub_002 is reconnecting",
        lastGoodAt: Date.parse("2026-10-22T11:58:00Z"),
        wordAt: 0,
        latencyMs: 12,
        latencyAt: 0,
      },
    ]);
  });

  it("test_contract_health_outage_reads_each_fault_with_its_last_good_time", () => {
    const body = vetHealthReport(payload("health_outage"));
    const records = mergeComponents(
      body === null ? undefined : { body, at: 0 },
      NO_WORDS,
      undefined,
    );
    const faults = records.filter((r) => r.state !== "healthy");
    expect(faults.map((r) => [r.name, r.state, r.lastGoodAt])).toEqual([
      ["postgres", "down", Date.parse("2026-10-22T11:50:00Z")],
      ["questdb", "down", undefined],
      ["bybit_public_ws", "degraded", Date.parse("2026-10-22T11:55:00Z")],
      ["disk", "warning", Date.parse("2026-10-22T11:55:00Z")],
    ]);
    expect(body).toMatchObject({ overall: "down", version: "fixture", uptime_seconds: 3600 });
  });
});
