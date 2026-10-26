/**
 * C-6.2 consumer contract (#2725): the web client reads the `Forbidden` examples `stepUpRequired`
 * and `stepUpRequiredTypedConfirmation` of `docs/plan/22-api-openapi.yaml` through the generated
 * `packages/protocol` types, and its `POST /auth/step-up` body is the generated request body.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  STEP_UP_REQUIRED,
  isStaleChallenge,
  readChallenge,
  type StepUpGranted,
  type StepUpProblem,
  type StepUpRequestBody,
} from "../../src/features/stepUp/challenge";

const SPEC = resolve(import.meta.dirname, "../../../../docs/plan/22-api-openapi.yaml");

/**
 * The flow mapping under `<name>:` / `value:` in the spec. The examples are one-level flow maps of
 * scalars (`key: value,` per line), so this reads exactly that shape and fails on anything else.
 */
function example(name: string): Record<string, unknown> {
  const lines = readFileSync(SPEC, "utf8").split("\n");
  const at = lines.findIndex((line) => line.trim() === `${name}:`);
  if (at < 0) throw new Error(`example ${name} not found`);
  const open = lines.findIndex((line, i) => i > at && line.trim() === "{");
  const close = lines.findIndex((line, i) => i > open && line.trim() === "}");
  if (lines[at + 2]?.trim() !== "value:" || open !== at + 3 || close < 0) {
    throw new Error(`example ${name} is not a one-level flow map`);
  }
  const out: Record<string, unknown> = {};
  for (const line of lines.slice(open + 1, close)) {
    const match = /^\s*([a-z_]+):\s*(.*?),?$/.exec(line);
    if (match === null) throw new Error(`unreadable example line: ${line}`);
    const [, key, raw] = match as unknown as [string, string, string];
    out[key] =
      raw === "null"
        ? null
        : /^\d+$/.test(raw)
          ? Number(raw)
          : raw.startsWith('"')
            ? (JSON.parse(raw) as string)
            : raw;
  }
  return out;
}

describe("step-up challenge consumer contract (C-6.2, #2304)", () => {
  it("test_contract_stepUpRequired_example_reads_as_a_challenge_without_target", () => {
    const body = example("stepUpRequired");
    const typed: StepUpProblem = body as StepUpProblem;
    expect(typed.code).toBe(STEP_UP_REQUIRED);
    expect(readChallenge(body)).toEqual({
      challengeId: "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b",
      expiresAt: "2026-09-14T10:36:02Z",
      actionClass: "killswitch",
      actionSummary: "Release kill switch, scope global",
      target: null,
    });
  });

  it("test_contract_stepUpRequiredTypedConfirmation_example_carries_the_target", () => {
    const challenge = readChallenge(example("stepUpRequiredTypedConfirmation"));
    expect(challenge).toEqual({
      challengeId: "0c9b8a7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d",
      expiresAt: "2026-09-14T10:36:02Z",
      actionClass: "keys",
      actionSummary: "Rotate API key for account 'sub_002' (live, UID 1001234)",
      target: "sub_002",
    });
  });

  it("test_contract_non_challenge_bodies_are_not_challenges", () => {
    expect(readChallenge(null)).toBeNull();
    expect(readChallenge({ code: "forbidden" })).toBeNull();
    expect(readChallenge({ code: STEP_UP_REQUIRED, action_class: "keys" })).toBeNull();
    expect(
      readChallenge({ ...example("stepUpRequired"), action_summary: undefined })?.actionSummary,
    ).toBeNull();
  });

  it("test_contract_stale_challenge_rules_are_the_spec_rules", () => {
    const spec = readFileSync(SPEC, "utf8");
    for (const rule of ["challenge_expired", "challenge_required"]) {
      expect(spec).toContain(`errors: [{field: challenge_id, rule: ${rule}}]`);
      expect(isStaleChallenge(400, { errors: [{ field: "challenge_id", rule }] })).toBe(true);
    }
    expect(isStaleChallenge(400, { errors: [{ field: "code", rule: "pattern" }] })).toBe(false);
    expect(isStaleChallenge(422, { errors: [{ rule: "challenge_expired" }] })).toBe(false);
    expect(isStaleChallenge(400, { errors: "x" })).toBe(false);
  });

  it("test_contract_types_are_the_generated_ones", () => {
    type Op = generated.rest.operations["authStepUp"];
    expectTypeOf<StepUpRequestBody>().toEqualTypeOf<
      Op["requestBody"]["content"]["application/json"]
    >();
    expectTypeOf<StepUpRequestBody["challenge_id"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<StepUpGranted["action_class"]>().toEqualTypeOf<string>();
    expectTypeOf<StepUpProblem>().toEqualTypeOf<generated.rest.components["schemas"]["Problem"]>();
  });
});
