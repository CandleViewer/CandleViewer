import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// E13-T03 (#427): the client's reading of the closed indicator-presets contract (C-6.2), on the
// generated REST types. Nothing serves these operations yet; the implementation PR does. The
// expectTypeOf checks bind under `pnpm typecheck` (tsconfig.json includes test/), not the vitest
// run; the runtime expects only keep the sample values in use.
type Schemas = generated.rest.components["schemas"];
type Input = Schemas["IndicatorPresetInput"];
type Preset = Schemas["IndicatorPreset"];
type Style = Schemas["IndicatorPresetStyle"];
type Operations = generated.rest.operations;
type Statuses<Op extends keyof Operations> = keyof Operations[Op]["responses"];

const atr = {
  name: "ATR 14",
  indicator_code: "atr",
  params: { n: 14 },
  style: {},
  pane_target: "subpane",
  is_favourite: false,
} satisfies Input;

describe("indicator presets (consumer side, 22-api-openapi /indicator-presets)", () => {
  it("writes a closed input: is_favourite, a pane target and no server-managed field", () => {
    expect(atr.params).toEqual({ n: 14 });
    expectTypeOf<Input["pane_target"]>().toEqualTypeOf<"overlay" | "subpane">();
    expectTypeOf<Input>().not.toHaveProperty("is_default");
    expectTypeOf<Input>().not.toHaveProperty("is_builtin");
    expectTypeOf<Input>().not.toHaveProperty("owner_user_id");
  });

  it("takes no style token until E13-D04 publishes the vocabulary", () => {
    expectTypeOf<Style>().toEqualTypeOf<Record<string, never>>();
    expectTypeOf<{ line: string }>().not.toExtend<Style>();
    expectTypeOf<Pick<Input, "style">>().toEqualTypeOf<{ style?: Style }>(); // omitted means {}
    expectTypeOf<Preset["style"]>().toEqualTypeOf<Style>();
  });

  it("reads a built-in with every field present, a null owner and a read-only is_builtin", () => {
    const at = "2026-10-20T12:00:00.000000Z";
    const id = "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c";
    const builtin: Preset = {
      ...atr,
      id,
      owner_user_id: null,
      is_builtin: true,
      created_at: at,
      updated_at: at,
    };
    expect(builtin.owner_user_id).toBeNull();
    expectTypeOf<Required<Preset>>().toEqualTypeOf<Preset>();
    expectTypeOf<Preset["owner_user_id"]>().toEqualTypeOf<string | null>();
    expectTypeOf<Pick<Preset, "is_builtin">>().toEqualTypeOf<{ readonly is_builtin: boolean }>();
  });

  it("declares every refusal of each operation, and no read by id", () => {
    type Refusals = 401 | 403 | 404 | 422 | 503;
    expectTypeOf<Statuses<"listIndicatorPresets">>().toEqualTypeOf<200 | Refusals>();
    expectTypeOf<Statuses<"createIndicatorPreset">>().toEqualTypeOf<201 | 409 | 413 | Refusals>();
    expectTypeOf<Statuses<"updateIndicatorPreset">>().toEqualTypeOf<200 | 409 | 413 | Refusals>();
    expectTypeOf<Statuses<"deleteIndicatorPreset">>().toEqualTypeOf<204 | Refusals>();
    expectTypeOf<"getIndicatorPreset">().not.toExtend<keyof Operations>();
  });

  it("carries a bundle's presets as input objects, never as stored presets", () => {
    type BundlePresets = NonNullable<Schemas["WorkspaceBundle"]["indicator_presets"]>;
    expectTypeOf<BundlePresets>().toEqualTypeOf<Input[]>();
  });
});
