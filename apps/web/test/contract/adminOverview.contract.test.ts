/**
 * C-6.2 consumer contract (E42-S01, #1022): SCR-120 reads the bodies the server's own tests pin for
 * `getAdminOverview` and `getHealth` (`services/api/tests/fixtures/admin/payloads`, E42-Q01's
 * HEALTH-RECORDER-DOWN / -HANG and the health payloads) through the generated `packages/protocol`
 * types, and each lands on the tile state E42-D03 §6 draws for it.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  vetHealth,
  vetOverview,
  type AdminOverview,
  type HealthReport,
} from "../../src/features/admin/overview/adminReads";
import type { AdminReadState, ReadEntry } from "../../src/features/admin/overview/readStore";
import { BANDS, healthTile, tileModel } from "../../src/features/admin/overview/tileModels";

const PAYLOADS = resolve(
  import.meta.dirname,
  "../../../../services/api/tests/fixtures/admin/payloads",
);
const payload = (name: string): unknown =>
  JSON.parse(readFileSync(resolve(PAYLOADS, `${name}.json`), "utf8")) as unknown;

const IDLE = { phase: "idle", inFlight: false } as const;
function state(patch: Partial<Record<keyof AdminReadState, Partial<ReadEntry<unknown>>>>) {
  const ids = ["overview", "capacity", "health", "flags", "audit", "backups", "invites"] as const;
  return Object.fromEntries(
    ids.map((id) => [id, { ...IDLE, ...patch[id] }]),
  ) as unknown as AdminReadState;
}

describe("admin overview consumer contract (C-6.2)", () => {
  it("test_contract_overview_types_are_the_generated_ones", () => {
    expectTypeOf<AdminOverview>().toEqualTypeOf<
      generated.rest.components["schemas"]["AdminOverview"]
    >();
    expectTypeOf<HealthReport>().toEqualTypeOf<
      generated.rest.components["schemas"]["HealthReport"]
    >();
  });

  it.each([
    ["overview_recorder_hang", "timed out after 300 ms"],
    ["overview_recorder_down", "source failed"],
  ])("test_contract_%s_errs_the_recorder_tile_alone", (name, detail) => {
    const raw = payload(name) as Record<string, unknown>;
    const body = vetOverview(raw);
    expect(body).not.toBeNull();
    // Every slice the server sends is one the client reads: none is dropped as unknown.
    expect(Object.keys(body ?? {}).sort()).toEqual(
      Object.keys(raw)
        .filter((key) => key !== "incidents_open")
        .sort(),
    );
    const s = state({ overview: { phase: "ok", data: body, okAt: 0 } });
    const states = Object.fromEntries(
      BANDS.flat().map((key) => [key, tileModel(key, s, "demo").state]),
    );
    expect(tileModel("recorder", s, "demo")).toMatchObject({
      state: "error",
      detail,
      retry: ["overview"],
    });
    // The overview-fed tiles read normally; the others wait on reads this fixture is not.
    expect(states).toMatchObject({ trading: "ready", users: "ready", accounts: "ready" });
  });

  it("test_contract_health_degraded_reads_the_private_stream_degraded", () => {
    const body = vetHealth(payload("health_degraded"));
    expect(body).not.toBeNull();
    const model = healthTile(state({ health: { phase: "ok", data: body, okAt: 0 } }));
    expect(model).toMatchObject({
      state: "ready",
      tone: "warning",
      stateWord: "Degraded",
      detail: "bybit_private_ws fixture: the private stream for sub_002 is reconnecting",
      lastGoodAt: Date.parse("2026-10-22T11:58:00Z"),
      stopsWorking: "order and position updates may lag; REST reconcile runs.",
      asOf: Date.parse("2026-10-22T12:00:00Z"),
    });
  });

  it("test_contract_health_outage_reads_postgres_down_first", () => {
    const model = healthTile(
      state({ health: { phase: "ok", data: vetHealth(payload("health_outage")), okAt: 0 } }),
    );
    expect(model).toMatchObject({
      tone: "danger",
      stateWord: "Down",
      detail: "postgres unreachable",
      stopsWorking: "new orders are off; cancel and close still work.",
    });
    expect(model.rows.map((r) => r.label)).toEqual([
      "postgres",
      "questdb",
      "bybit_public_ws",
      "disk",
    ]);
  });
});
