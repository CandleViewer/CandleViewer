/**
 * C-6.2 consumer contract (E16-S01, BQ-5): the recorder client's fixtures are `22`'s examples, read out
 * of `docs/plan/22-api-openapi.yaml` here; its types are the generated ones; and every deck sentence
 * its refusals route to is a key of the E16-D06 deck (`docs/design/E16/E16-D06-copy.json`).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  REFUSAL_DECK_KEYS,
  isRecorderFrame,
  type AddRecordedSymbolBody,
  type DataCoverage,
  type Job,
  type JobAccepted,
  type PurgeBody,
  type RecordedSymbolPage,
  type RecorderFrame,
  type RecordingSessionPage,
  type RecordingStatus,
  type StorageUsage,
} from "../../src/features/recorder"; // the feature's public surface
import {
  addManual,
  frameHealthy,
  listTwo,
  purgeAnchoredBound,
  purgeJobRunning,
  statusHealthy,
  storageUsage,
} from "../features/recorder/fixtures";
import { example } from "./specExamples";

const ROOT = resolve(import.meta.dirname, "../../../..");
const op = (id: string) => `operationId: ${id}`;

describe("recorder client consumer contract (C-6.2, E16-S01)", () => {
  it.each([
    ["listRecordedSymbols `two`", op("listRecordedSymbols"), "two", listTwo],
    ["getRecordingStatus `healthy`", op("getRecordingStatus"), "healthy", statusHealthy],
    ["getStorageUsage `usage`", op("getStorageUsage"), "usage", storageUsage],
    ["addRecordedSymbol `manual`", op("addRecordedSymbol"), "manual", addManual],
    ["purgeRecordedData `jobRunning`", op("purgeRecordedData"), "jobRunning", purgeJobRunning],
    [
      "purgeRecordedData `anchoredBound`",
      op("purgeRecordedData"),
      "anchoredBound",
      purgeAnchoredBound,
    ],
  ])("the fixture is %s, as `22` has it", (_, anchor, name, fixture) => {
    expect(example(anchor, name)).toEqual(fixture);
  });

  it("the `recorder` frame fixture carries the same status and storage, and passes the guard", () => {
    expect(isRecorderFrame(frameHealthy)).toBe(true);
    const tiers = storageUsage.tiers.filter(({ tier }) => tier !== "postgres");
    expect(frameHealthy.storage.used_bytes).toBe(tiers.reduce((sum, t) => sum + t.used_bytes, 0));
    expect(frameHealthy.symbols.map((row) => [row.symbol, row.state])).toEqual(
      statusHealthy.symbols.map((row) => [row.symbol, row.state]),
    );
  });

  it("every deck sentence a refusal routes to is a key of the E16-D06 deck", () => {
    const deck = JSON.parse(
      readFileSync(resolve(ROOT, "docs/design/E16/E16-D06-copy.json"), "utf8"),
    ) as { strings: Record<string, unknown> };
    expect(REFUSAL_DECK_KEYS.filter((key) => !(key in deck.strings))).toEqual([]);
  });

  it("the client's types are the generated ones (C-4.16)", () => {
    type Ops = generated.rest.operations;
    type Json<T> = T extends { content: { "application/json": infer B } } ? B : never;
    expectTypeOf<RecordedSymbolPage>().toEqualTypeOf<
      Json<Ops["listRecordedSymbols"]["responses"][200]>
    >();
    expectTypeOf<RecordingStatus>().toEqualTypeOf<
      Json<Ops["getRecordingStatus"]["responses"][200]>
    >();
    expectTypeOf<StorageUsage>().toEqualTypeOf<Json<Ops["getStorageUsage"]["responses"][200]>>();
    expectTypeOf<RecordingSessionPage>().toEqualTypeOf<
      Json<Ops["listRecordingSessions"]["responses"][200]>
    >();
    expectTypeOf<DataCoverage>().toEqualTypeOf<Json<Ops["getDataCoverage"]["responses"][200]>>();
    expectTypeOf<Job>().toEqualTypeOf<Json<Ops["getJob"]["responses"][200]>>();
    expectTypeOf<JobAccepted>().toEqualTypeOf<Json<Ops["purgeRecordedData"]["responses"][202]>>();
    expectTypeOf<AddRecordedSymbolBody>().toEqualTypeOf<
      Json<Ops["addRecordedSymbol"]["requestBody"]>
    >();
    expectTypeOf<PurgeBody>().toEqualTypeOf<Json<Ops["purgeRecordedData"]["requestBody"]>>();
    expectTypeOf<RecorderFrame>().toEqualTypeOf<generated.ws.Recorder>();
  });
});
