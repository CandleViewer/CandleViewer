import type { Comparison, RuleIr as GeneratedRuleIr } from "@candleviewer/protocol/rule-ir";
import type { FormReason, isFormRepresentable } from "@candleviewer/rule-graph";
import { describe, expect, expectTypeOf, it } from "vitest";
import type * as Api from "../src/index.js";

// The public entry is the package's contract: pin what it exports at runtime. The types are
// erased, so `tsc` (typecheck; test/ is in tsconfig's include) holds the second case.
describe("the public entry", () => {
  it("exports exactly the limits and the pointer helpers", async () => {
    expect(Object.keys(await import("../src/index.js")).sort()).toEqual([
      "PointerError",
      "RULE_LIMITS",
      "checkImportSelection",
      "checkRuleShape",
      "cloneJson",
      "countValues",
      "encodePointer",
      "encodeRequestBody",
      "getAt",
      "hasAt",
      "jsonDepthExceeds",
      "parsePointer",
      "parseRuleJson",
      "setAt",
      "utf8ByteLength",
    ]);
  });

  it("re-exports the generated RuleIr and builds the model on the generated types", () => {
    expectTypeOf<Api.RuleIr>().toEqualTypeOf<GeneratedRuleIr>();
    expectTypeOf<Api.ConditionRow["comparison"]>().toEqualTypeOf<Comparison>();
    expectTypeOf<Api.FormModel["base"]>().toEqualTypeOf<GeneratedRuleIr>();
    expectTypeOf<Api.FormModel["scope"]>().toEqualTypeOf<GeneratedRuleIr["scope"]>();
    expectTypeOf<Api.FormModel["trigger"]>().toEqualTypeOf<GeneratedRuleIr["trigger"]>();
    expectTypeOf<Api.Presentation>().toEqualTypeOf<
      Readonly<Pick<GeneratedRuleIr, "graph_layout" | "editor">>
    >();
    expectTypeOf<Api.ConditionEntry["kind"]>().toEqualTypeOf<"row" | "group" | "opaque">();
    expectTypeOf<Api.GroupMode>().toEqualTypeOf<"all_of" | "any_of">();
    expectTypeOf<Api.ReadOnlyReason>().toEqualTypeOf<Api.LimitRefusal>();
    expectTypeOf<keyof Api.FormModel>().toEqualTypeOf<
      | "base"
      | "scope"
      | "trigger"
      | "conditionGroups"
      | "actions"
      | "options"
      | "presentation"
      | "opaqueRegions"
      | "formReasons"
      | "readOnly"
    >();
    // BQ-02 rider a: the whole-rule verdict is rule-graph's own, not a second subset.
    expectTypeOf<Api.FormReason>().toEqualTypeOf<FormReason>();
    expectTypeOf<Api.FormModel["formReasons"][number]>().toEqualTypeOf<
      ReturnType<typeof isFormRepresentable>[number]
    >();
    expectTypeOf<keyof Api.OpaqueRegion>().toEqualTypeOf<
      "id" | "irPointer" | "rawNode" | "plainLanguageSummary" | "reason"
    >();
  });
});
