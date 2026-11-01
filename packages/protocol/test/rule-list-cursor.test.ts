import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// #2291 (SR-051): the client's reading of `listRules`' answer to a cursor that is not a rule id
// (C-6.2). 22 declares a 400 on `listRules` through the shared `BadRequest` response, whose body
// is a problem carrying `invalid_cursor`. The expectTypeOf checks bind under `pnpm typecheck`
// (tsconfig.json includes test/), not the vitest run: an answer 22 stops declaring is a type error
// there. The runtime expect only keeps the sample value in use.
type Operations = generated.rest.operations;
type Components = generated.rest.components;
type Problem = Components["schemas"]["Problem"];
type Answer<
  Op extends keyof Operations,
  Status extends keyof Operations[Op]["responses"],
> = Operations[Op]["responses"][Status];
type ProblemBody<R> = R extends { content: { "application/problem+json": infer P } } ? P : never;

const malformedCursor = {
  type: "https://candleviewer.local/errors/invalid_cursor",
  title: "Pagination cursor is malformed or expired",
  status: 400,
  code: "invalid_cursor",
  detail: "The cursor is not a rule id.",
} satisfies Problem;

describe("rules list cursor (consumer side, 22-api-openapi listRules)", () => {
  it("answers 400 with a problem body for a cursor that is not a rule id", () => {
    type BadRequest = Components["responses"]["BadRequest"];
    expectTypeOf<Answer<"listRules", 400>>().toEqualTypeOf<BadRequest>();
    expectTypeOf<ProblemBody<Answer<"listRules", 400>>>().toEqualTypeOf<Problem>();
    expect([malformedCursor.status, malformedCursor.code]).toEqual([400, "invalid_cursor"]);
  });
});
