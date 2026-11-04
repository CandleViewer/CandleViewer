import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";
import { RULE_IR_SCHEMA, type RuleScope } from "../src/generated/ruleIr/index.js";

// #5691 (E35, C-12.4): the client's reading of a rule scope's lists (C-6.2), at most 100 accounts
// and 3 environments, each once. The account bound is above the generator's tuple threshold, so it
// stays a plain `string[]`; the type checks bind under `pnpm typecheck` (tsconfig.json: test/).
type RestScope = generated.rest.components["schemas"]["RuleIrScope"];
type Member = Record<string, unknown>;

const BOUND = 100;
const ENVIRONMENTS = 3;

describe("a rule scope's lists (consumer side, 22 RuleIrScope and rule-ir.json)", () => {
  it("are published with their bounds and their uniqueness", () => {
    const defs = RULE_IR_SCHEMA["$defs"] as Record<string, unknown>;
    const scope = defs["RuleScope"] as {
      properties: { account_ids: Member; environments: Member };
    };
    expect(scope.properties.account_ids["maxItems"]).toBe(BOUND);
    expect(scope.properties.account_ids["uniqueItems"]).toBe(true);
    expect(scope.properties.environments["maxItems"]).toBe(ENVIRONMENTS);
    expect(scope.properties.environments["uniqueItems"]).toBe(true);
  });

  it("types the account list as a plain string array on both surfaces", () => {
    expectTypeOf<RuleScope["account_ids"]>().toEqualTypeOf<string[] | undefined>();
    expectTypeOf<RestScope["account_ids"]>().toEqualTypeOf<string[]>();
  });

  it("types the environment list as at most three entries", () => {
    const three: RuleScope["environments"] = ["demo", "live", "testnet"];
    // @ts-expect-error: a scope names at most three environments
    const four: RuleScope["environments"] = ["demo", "live", "testnet", "demo"];
    expect([three, four]).toHaveLength(2);
  });
});
