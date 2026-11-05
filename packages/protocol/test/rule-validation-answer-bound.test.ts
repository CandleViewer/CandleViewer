import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// #5879 (E35 hardening): the client's reading of the bounded validation answers (C-6.2). 22 lists
// at most 50 issues in `validateRule`'s answer and in `compileRule`'s, the errors first, and each
// answer counts every issue found in `issues_total`, `compileRule`'s 422 `rule_ir_invalid`
// included; a round trip lists at most 50 differences and counts them in `diff_total`. The
// expectTypeOf checks bind under `pnpm typecheck` (tsconfig.json includes test/), not the vitest
// run; the runtime expects keep the sample values in use.
type Operations = generated.rest.operations;
type Components = generated.rest.components;
type Problem = Components["schemas"]["Problem"];
type Result = Components["schemas"]["RuleValidationResult"];
type Issue = Components["schemas"]["RuleValidationIssue"];
type Compiled = Operations["compileRule"]["responses"][200]["content"]["application/json"];
type RoundTrip = NonNullable<Compiled["round_trip"]>;

const BOUND = 50;

const issue: Issue = {
  path: "scope.symbols[0]",
  code: "schema_error",
  message: "String should match pattern '^[A-Z0-9]{4,20}$'",
  severity: "error",
  class: "syntax",
};

const validated = {
  valid: false,
  errors: Array.from({ length: BOUND }, () => issue),
  warnings: [],
  issues_total: 120,
} satisfies Result;

const compiled = {
  ir_hash: "0f",
  issues: [issue],
  issues_total: 1,
  blocks_arming: true,
} satisfies Compiled;

const trip = {
  match: false,
  diff: Array.from({ length: BOUND }, (_, i) => ({ path: `/conditions/set_values/${i}` })),
  diff_total: 60,
} satisfies RoundTrip;

const refused = {
  type: "https://candleviewer.local/errors/rule_ir_invalid",
  title: "Rule intermediate representation failed semantic validation",
  status: 422,
  code: "rule_ir_invalid",
  detail: "120 errors in the rule IR.",
  errors: [{ field: "scope.symbols[0]", rule: "schema_error", message: "Not a symbol." }],
  issues_total: 120,
} satisfies Problem;

describe("bounded validation answers (consumer side, 22-api-openapi /rules)", () => {
  it("reads every answer's count of the issues found, beside the ones it lists", () => {
    expectTypeOf<Result["issues_total"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Compiled["issues_total"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Problem["issues_total"]>().toEqualTypeOf<number | undefined>();
    expect(validated.errors.length + validated.warnings.length).toBe(BOUND);
    expect(validated.issues_total).toBeGreaterThan(BOUND);
  });

  it("keeps the issue lists of both answers and the 422's errors as before", () => {
    expectTypeOf<Result["errors"]>().toEqualTypeOf<Issue[]>();
    expectTypeOf<Result["warnings"]>().toEqualTypeOf<Issue[]>();
    expectTypeOf<Compiled["issues"]>().toEqualTypeOf<Issue[] | undefined>();
    expectTypeOf<Operations["compileRule"]["responses"][422]>().toEqualTypeOf<
      Components["responses"]["RuleIrInvalid"]
    >();
    expect(compiled.issues_total).toBe(compiled.issues.length);
    expect(refused.issues_total).toBeGreaterThan(refused.errors.length);
  });

  it("reads a round trip's count of every difference, beside the ones it lists", () => {
    expectTypeOf<RoundTrip["diff_total"]>().toEqualTypeOf<number | undefined>();
    expect(trip.diff).toHaveLength(BOUND);
    expect(trip.diff_total).toBeGreaterThan(trip.diff.length);
  });
});
