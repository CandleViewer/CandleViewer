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

const ROOT = resolve(import.meta.dirname, "../../../..");
const SPEC = readFileSync(resolve(ROOT, "docs/plan/22-api-openapi.yaml"), "utf8").split("\n");

interface Line {
  readonly indent: number;
  readonly text: string;
}
const KEY = /^([a-z_][\w-]*):(?: (.*))?$/;

/** A plain or double-quoted scalar of the examples; anything else throws rather than guess. */
function scalar(text: string): unknown {
  if (text === "null" || text === "true" || text === "false") return JSON.parse(text);
  if (/^-?\d+$/.test(text)) return Number(text);
  if (text.startsWith('"')) return JSON.parse(text) as string;
  if (/^[\w.-]+$/.test(text)) return text;
  throw new Error(`unread scalar: ${text}`);
}

/** A flow map or sequence (`{ a: 1, b: [x, y] }`), possibly joined from several lines. */
function flow(source: string): unknown {
  const tokens = (source.match(/"(?:[^"\\]|\\.)*"|[{}[\],:]|[^\s{}[\],:"][^{}[\],:]*/g) ?? []).map(
    (token) => token.trim(),
  );
  let at = 0;
  const take = (): string => tokens[at++] ?? "";
  const value = (): unknown => {
    const open = take();
    if (open !== "{" && open !== "[") return scalar(open);
    const out: Record<string, unknown> = {};
    const list: unknown[] = [];
    while (tokens[at] !== (open === "{" ? "}" : "]")) {
      if (at >= tokens.length) throw new Error(`unclosed flow: ${source}`);
      if (open === "{") {
        const key = take();
        if (take() !== ":") throw new Error(`no ':' after ${key}`);
        out[key] = value();
      } else list.push(value());
      if (tokens[at] === ",") at += 1;
    }
    at += 1;
    return open === "{" ? out : list;
  };
  const out = value();
  if (at !== tokens.length) throw new Error(`text after the flow: ${source}`);
  return out;
}

/** Each child of a block: its head line at the block's indent and the deeper lines after it. */
function children(lines: readonly Line[]): Line[][] {
  const indent = lines[0]?.indent;
  const out: Line[][] = [];
  for (const line of lines) {
    if (line.indent === indent) out.push([line]);
    else out.at(-1)?.push(line);
  }
  return out;
}

/** A block: flow, a sequence (`- …`) or a map (`key: …`), by its first line. */
function block(lines: readonly Line[]): unknown {
  const head = lines[0]?.text ?? "";
  if (/^[[{]/.test(head)) return flow(lines.map((line) => line.text).join(" "));
  if (head.startsWith("- ")) {
    return children(lines).map(([first, ...rest]) => {
      const item = first?.text.slice(2) ?? "";
      if (/^[[{]/.test(item)) return flow([item, ...rest.map((line) => line.text)].join(" "));
      if (!KEY.test(item)) return scalar(item);
      return block([{ indent: (first?.indent ?? 0) + 2, text: item }, ...rest]);
    });
  }
  const map: Record<string, unknown> = {};
  for (const [first, ...rest] of children(lines)) {
    const [, key, inline] = KEY.exec(first?.text ?? "") ?? [];
    if (key === undefined) throw new Error(`unread line: ${first?.text}`);
    const text = [inline ?? "", ...rest.map((line) => line.text)].join(" ").trim();
    map[key] =
      inline === undefined ? block(rest) : /^[[{]/.test(inline) ? flow(text) : scalar(inline);
  }
  return map;
}

/** The `value` of the first example called `name` after the line `anchor` in `22`. */
function example(anchor: string, name: string): unknown {
  const from = SPEC.findIndex((line) => line.trim() === anchor);
  const at = SPEC.findIndex((line, i) => i > from && line.trim().startsWith(`${name}:`));
  if (from < 0 || at < 0) throw new Error(`example ${name} after ${anchor} not found`);
  const indent = SPEC[at]?.search(/\S/) ?? 0;
  const end = SPEC.findIndex(
    (line, i) => i > at && line.trim() !== "" && line.search(/\S/) <= indent,
  );
  const lines = SPEC.slice(at, end)
    .filter((line) => line.trim() !== "")
    .map((line) => ({ indent: line.search(/\S/), text: line.trim() }));
  return (block(lines) as Record<string, { value?: unknown }>)[name]?.value;
}

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
