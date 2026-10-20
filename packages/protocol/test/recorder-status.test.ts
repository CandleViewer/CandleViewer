import { describe, expect, it, expectTypeOf } from "vitest";
import { generated } from "../src/index.js";

// E16-D01 (#323, #492): the client's reading of the additive recorder status fields (C-6.2), on
// the generated types; nothing serves them yet (E16-T08). The expectTypeOf checks bind under
// `pnpm typecheck` (tsconfig.json includes test/), not the vitest run.
type Frame = generated.ws.Recorder;
type Row = Frame["symbols"][number];
type Storage = NonNullable<Frame["storage"]>;
type Rest = generated.rest.components["schemas"];
type StatusRow = NonNullable<Rest["RecordingStatus"]["symbols"]>[number];
type Listed =
  generated.rest.operations["listRecordedSymbols"]["responses"][200]["content"]["application/json"];
type Refusal = "symbol_cap" | "disk_pressure" | "chart_open" | "position_open" | null;
type Marks = { lingering?: boolean; linger_until?: string | null; refusal?: Refusal };
type Gate = {
  cap_bytes?: number;
  level?: 0 | 1 | 2 | 3;
  write_gate?: "open" | "closed";
  write_gate_reason?: "disk_halt" | "volume_refused" | null;
};
type Policy = Rest["RecorderPolicySettings"];

describe("recorder status fields (consumer side, 23-ws-protocol §15.8, E16-D01)", () => {
  it("decodes a frame with and without the new fields", () => {
    const old: Frame = { overall: "healthy", symbols: [{ symbol: "ETHUSDT", state: "recording" }] };
    const row: Row = { symbol: "SOLUSDT", state: "idle", refusal: "symbol_cap" };
    const gate: Storage = { level: 3, write_gate: "closed", write_gate_reason: "disk_halt" };
    expect([old.role_restricted, old.symbols[0]?.refusal]).toEqual([undefined, undefined]);
    expect([row.refusal, gate.level, gate.write_gate]).toEqual(["symbol_cap", 3, "closed"]);
  });

  it("types the new fields as optional, with closed value sets, on WS and REST alike", () => {
    expectTypeOf<Frame["role_restricted"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<Rest["RecordingStatus"]["role_restricted"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<Listed["role_restricted"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<Pick<Storage, keyof Gate>>().toEqualTypeOf<Gate>();
    expectTypeOf<Pick<Rest["StorageUsage"], keyof Gate>>().toEqualTypeOf<Gate>();
    expectTypeOf<Pick<StatusRow, keyof Marks>>().toEqualTypeOf<Marks>();
    expectTypeOf<Pick<Rest["RecordedSymbol"], keyof Marks>>().toEqualTypeOf<Marks>();
    expectTypeOf<Row["lingering"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<Row["linger_until_ms"]>().toEqualTypeOf<number | null | undefined>();
    expectTypeOf<Row["refusal"]>().toEqualTypeOf<Refusal | undefined>();
    expectTypeOf<Row>().not.toHaveProperty("linger_until"); // the REST spelling
    expectTypeOf<NonNullable<Frame["policy"]>>().toEqualTypeOf<Policy>(); // one shape, both ways
    expectTypeOf<Rest["RecordingStatus"]["policy"]>().toEqualTypeOf<Policy | undefined>();
    expectTypeOf<Policy["halt_pct"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Policy["autorecord_enabled"]>().toEqualTypeOf<boolean | undefined>();
  });
});
