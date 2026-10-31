/**
 * C-6.2 consumer contract (E16-S04, #486): the health fixture is `22`'s example, read out of
 * `docs/plan/22-api-openapi.yaml`; the import's `202` and the job results have no example in `22`,
 * so their fixtures are held to the generated types and to their schema's `required` keys; the
 * client's types are the generated ones (C-4.16); and each job's result is typed by the action that
 * issued its id (BQ-4, BQ-11): a compaction's is `CompactionRunResult` though its `kind` is a
 * sweep's.
 */
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  recorderApi,
  type ApiResult,
  type ArchiveImportResult,
  type CompactionRunResult,
  type HealthReport,
  type ImportBody,
  type JobAccepted,
  type JobOf,
  type RetentionPurgeResult,
} from "../../src/features/recorder"; // the feature's public surface
import {
  compactionResult,
  healthDegraded,
  importAccepted,
  importResult,
  purgeResult,
} from "../features/recorder/fixtures";
import { example, schemaRequired } from "./specExamples";

type Ops = generated.rest.operations;
type Schemas = generated.rest.components["schemas"];
type Json<T> = T extends { content: { "application/json": infer B } } ? B : never;

describe("storage client consumer contract (C-6.2, E16-S04)", () => {
  it("the fixture is getHealth `degraded`, as `22` has it", () => {
    expect(example("operationId: getHealth", "degraded")).toEqual(healthDegraded);
  });

  it.each([
    ["ArchiveImportResult", importResult],
    ["CompactionRunResult", compactionResult],
    ["RetentionPurgeResult", purgeResult],
  ])("the %s fixture carries exactly `22`'s keys", (schema, fixture) => {
    expect(Object.keys(fixture).sort()).toEqual(schemaRequired(schema).sort());
  });

  it("the import's 202 fixture is the generated 202 body (`22` gives it no example)", () => {
    expect(importAccepted).toEqual({ job_id: expect.stringMatching(/^[0-9a-f-]{36}$/) });
    expectTypeOf(importAccepted).toExtend<Json<Ops["importTradeArchive"]["responses"][202]>>();
  });

  it("the client's types are the generated ones (C-4.16)", () => {
    expectTypeOf<HealthReport>().toEqualTypeOf<Json<Ops["getHealth"]["responses"][200]>>();
    expectTypeOf<ImportBody>().toEqualTypeOf<Json<Ops["importTradeArchive"]["requestBody"]>>();
    expectTypeOf<JobAccepted>().toEqualTypeOf<Json<Ops["importTradeArchive"]["responses"][202]>>();
    expectTypeOf<ArchiveImportResult>().toEqualTypeOf<Schemas["ArchiveImportResult"]>();
    expectTypeOf<CompactionRunResult>().toEqualTypeOf<Schemas["CompactionRunResult"]>();
    expectTypeOf<RetentionPurgeResult>().toEqualTypeOf<Schemas["RetentionPurgeResult"]>();
    expectTypeOf<NonNullable<JobOf<"import">["result"]>>().toEqualTypeOf<
      Schemas["ArchiveImportResult"]
    >();
    expectTypeOf<NonNullable<JobOf<"compact">["result"]>>().toEqualTypeOf<
      Schemas["CompactionRunResult"]
    >();
    expectTypeOf<NonNullable<JobOf<"purge">["result"]>>().toEqualTypeOf<
      Schemas["RetentionPurgeResult"]
    >();
    expectTypeOf(recorderApi.importArchive).returns.resolves.toEqualTypeOf<
      ApiResult<JobAccepted>
    >();
    expectTypeOf(recorderApi.health).returns.resolves.toEqualTypeOf<ApiResult<HealthReport>>();
  });
});
