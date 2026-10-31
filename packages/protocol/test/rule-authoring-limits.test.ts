import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// #4834 (E35 authoring limits): the client's reading of the `/rules` limits (C-6.2). 22 declares a
// 429 on both checks, a 409 on `createRule` and a 422 on `setActiveRuleVersion`. The expectTypeOf
// checks bind under `pnpm typecheck` (tsconfig.json includes test/), not the vitest run: an answer
// 22 stops declaring is a type error there. The runtime expects only keep the sample values in use.
type Operations = generated.rest.operations;
type Components = generated.rest.components;
type Problem = Components["schemas"]["Problem"];
type Answer<
  Op extends keyof Operations,
  Status extends keyof Operations[Op]["responses"],
> = Operations[Op]["responses"][Status];
type ProblemBody<R> = R extends { content: { "application/problem+json": infer P } } ? P : never;

const limited = {
  type: "https://candleviewer.local/errors/rate_limited",
  title: "Per-user API rate limit exceeded",
  status: 429,
  code: "rate_limited",
  retry_after_seconds: 1,
} satisfies Problem;

const storedRuleCap = {
  type: "https://candleviewer.local/errors/conflict",
  title: "Concurrent modification or state conflict",
  status: 409,
  code: "conflict",
  errors: [{ rule: "limit_reached", message: "You have reached the limit of 200 saved rules." }],
} satisfies Problem;

const noteTooLong = {
  type: "https://candleviewer.local/errors/rule_ir_invalid",
  title: "Rule intermediate representation failed semantic validation",
  status: 422,
  code: "rule_ir_invalid",
  errors: [{ field: "note", rule: "max_length", message: "At most 280 characters." }],
} satisfies Problem;

describe("rule authoring limits (consumer side, 22-api-openapi /rules)", () => {
  it("answers 429 on both checks, with Retry-After and a problem body", () => {
    type Limited = Components["responses"]["RateLimited"];
    expectTypeOf<Answer<"validateRule", 429>>().toEqualTypeOf<Limited>();
    expectTypeOf<Answer<"compileRule", 429>>().toEqualTypeOf<Limited>();
    expectTypeOf<Limited["headers"]["Retry-After"]>().toEqualTypeOf<number>();
    expectTypeOf<ProblemBody<Limited>>().toEqualTypeOf<Problem>();
    expect(limited.retry_after_seconds).toBeGreaterThanOrEqual(1);
  });

  it("answers 409 on createRule with a problem body naming the rule", () => {
    expectTypeOf<ProblemBody<Answer<"createRule", 409>>>().toEqualTypeOf<Problem>();
    type Refusal = NonNullable<Problem["errors"]>[number];
    expectTypeOf<Refusal["rule"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<Refusal["message"]>().toEqualTypeOf<string | undefined>();
    expect(storedRuleCap.errors.map((e) => e.rule)).toEqual(["limit_reached"]);
  });

  it("answers 422 on every rule save, the activation included, by code and field", () => {
    type Invalid = Components["responses"]["RuleIrInvalid"];
    expectTypeOf<Answer<"createRule", 422>>().toEqualTypeOf<Invalid>();
    expectTypeOf<Answer<"updateRule", 422>>().toEqualTypeOf<Invalid>();
    expectTypeOf<Answer<"setActiveRuleVersion", 422>>().toEqualTypeOf<Invalid>();
    expectTypeOf<Answer<"compileRule", 422>>().toEqualTypeOf<Invalid>();
    expectTypeOf<ProblemBody<Invalid>>().toEqualTypeOf<Problem>();
    expect(noteTooLong.errors.map((e) => [e.field, e.rule])).toEqual([["note", "max_length"]]);
  });
});
