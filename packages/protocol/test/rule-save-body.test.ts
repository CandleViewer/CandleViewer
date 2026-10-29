import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// #4835 (E36-X01 G-12): the client's reading of the closed `/rules` save bodies (C-6.2). No member
// outside `ir` names an account: a rule's accounts travel in `ir.scope.account_ids`, and `ir`
// requires `scope`. The expectTypeOf checks bind under `pnpm typecheck` (tsconfig.json includes
// test/), not the vitest run; the runtime expect only keeps the sample value in use.
type Schemas = generated.rest.components["schemas"];
type Create = Schemas["RuleInput"];
type Update = Schemas["RuleUpdateInput"];
type Scope = Schemas["RuleIrScope"];
type Operations = generated.rest.operations;
type Body<Op extends keyof Operations> = NonNullable<
  Operations[Op]["requestBody"]
>["content"]["application/json"];
type AccountNamed<T> = Extract<Lowercase<keyof T & string>, `${string}account${string}`>;

const scope = {
  level: "account",
  account_ids: ["a1000000-0000-4000-8000-000000000001"],
  symbols: [],
  applies_to: "any",
  environments: ["demo"],
  exclude_algo_children: true,
} satisfies Scope;

describe("rule save bodies (consumer side, 22-api-openapi /rules)", () => {
  it("names no account outside ir and the rule's accounts in the required ir.scope", () => {
    expect(scope.account_ids).toHaveLength(1);
    expectTypeOf<Create>().not.toHaveProperty("bindings");
    expectTypeOf<Update>().not.toHaveProperty("bindings");
    expectTypeOf<AccountNamed<Create>>().toBeNever();
    expectTypeOf<AccountNamed<Update>>().toBeNever();
    expectTypeOf<Create["ir"]["scope"]>().toEqualTypeOf<Scope>();
    expectTypeOf<Scope["account_ids"]>().toEqualTypeOf<string[]>();
  });

  it("sends RuleInput to createRule and adds only expected_version on updateRule", () => {
    expectTypeOf<Body<"createRule">>().toEqualTypeOf<Create>();
    expectTypeOf<Body<"updateRule">>().toEqualTypeOf<Update>();
    expectTypeOf<Omit<Update, "expected_version">>().toEqualTypeOf<Create>();
    expectTypeOf<Update["expected_version"]>().toEqualTypeOf<number | undefined>();
  });
});
