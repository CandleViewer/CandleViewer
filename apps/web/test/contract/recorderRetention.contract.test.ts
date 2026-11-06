/**
 * C-6.2 consumer contract (E16-S03, #485): the retention calls' fixtures are `22`'s examples, read
 * out of `docs/plan/22-api-openapi.yaml`; the client's types are the generated ones (C-4.16); an
 * `apply_now` sweep's job result is `22`'s `RetentionSweepResult`, typed by the action that issued
 * its id, never by `kind` (BQ-4, BQ-11); and every `retention.refused.*` sentence of the E16-D06
 * deck is a refusal route of the client (E16-D06 §16.4 rows 2, 6, 8, 9 and 10).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  REFUSAL_DECK_KEYS,
  recorderApi,
  type ApiResult,
  type JobOf,
  type RetentionPoliciesBody,
  type RetentionPoliciesSaved,
  type RetentionPolicyList,
  type RetentionQuery,
  type RetentionSweepResult,
} from "../../src/features/recorder"; // the feature's public surface
import {
  retentionAppliedNow,
  retentionDefaults,
  retentionScheduled,
  sweepResult,
} from "../features/recorder/fixtures";
import { example, schemaRequired } from "./specExamples";

type Ops = generated.rest.operations;
type Schemas = generated.rest.components["schemas"];
type Json<T> = T extends { content: { "application/json": infer B } } ? B : never;

const DECK = resolve(import.meta.dirname, "../../../../docs/design/E16/E16-D06-copy.json");
const op = (id: string) => `operationId: ${id}`;

describe("retention client consumer contract (C-6.2, E16-S03)", () => {
  it.each([
    [
      "listRetentionPolicies `defaults`",
      op("listRetentionPolicies"),
      "defaults",
      retentionDefaults,
    ],
    [
      "setRetentionPolicies `scheduled`",
      op("setRetentionPolicies"),
      "scheduled",
      retentionScheduled,
    ],
    [
      "setRetentionPolicies `appliedNow`",
      op("setRetentionPolicies"),
      "appliedNow",
      retentionAppliedNow,
    ],
  ])("the fixture is %s, as `22` has it", (_, anchor, name, fixture) => {
    expect(example(anchor, name)).toEqual(fixture);
  });

  it("the sweep's result fixture carries exactly `22`'s RetentionSweepResult keys", () => {
    expect(Object.keys(sweepResult).sort()).toEqual(schemaRequired("RetentionSweepResult").sort());
  });

  it("every retention.refused.* sentence of the deck is a refusal route of the client", () => {
    const deck = JSON.parse(readFileSync(DECK, "utf8")) as { strings: Record<string, unknown> };
    const refused = (keys: readonly string[]) =>
      keys.filter((key) => key.startsWith("retention.refused.")).sort();
    expect(refused(REFUSAL_DECK_KEYS)).toEqual(refused(Object.keys(deck.strings)));
  });

  it("the client's types are the generated ones (C-4.16)", () => {
    expectTypeOf<RetentionPolicyList>().toEqualTypeOf<
      Json<Ops["listRetentionPolicies"]["responses"][200]>
    >();
    expectTypeOf<RetentionPoliciesBody>().toEqualTypeOf<
      Json<Ops["setRetentionPolicies"]["requestBody"]>
    >();
    expectTypeOf<RetentionPoliciesSaved>().toEqualTypeOf<
      Json<Ops["setRetentionPolicies"]["responses"][200]>
    >();
    expectTypeOf<RetentionQuery>().toEqualTypeOf<
      NonNullable<Ops["setRetentionPolicies"]["parameters"]["query"]>
    >();
    expectTypeOf<RetentionPoliciesSaved["job_id"]>().toEqualTypeOf<string | null>();
    expectTypeOf<RetentionSweepResult>().toEqualTypeOf<Schemas["RetentionSweepResult"]>();
    expectTypeOf<NonNullable<JobOf<"retention">["result"]>>().toEqualTypeOf<
      Schemas["RetentionSweepResult"]
    >();
    expectTypeOf(recorderApi.setRetention).returns.resolves.toEqualTypeOf<
      ApiResult<RetentionPoliciesSaved>
    >();
    expectTypeOf(recorderApi.retention).returns.resolves.toEqualTypeOf<
      ApiResult<RetentionPolicyList>
    >();
  });
});
