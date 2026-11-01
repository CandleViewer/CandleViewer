/**
 * E16-S01: the model's words and CMP-177's own copy of them hold together (#5309 A-09, B-11). The batch says the
 * model's words (SR-01) and a row draws CMP-177's, so each state's leading word is one and the same; CMP-177's five
 * T2 reasons are the deck's, which `copy.test.ts` holds to `E16-D06-copy.json`.
 */
import { describe, expect, it } from "vitest";
import { RECORDER_REASONS, recorderStatusColumns } from "@candleviewer/ui";
import { DECK } from "../../../src/features/recorder/copy";
import { rowData } from "../../../src/features/recorder/grid";
import { stateWords, type RecorderRow } from "../../../src/features/recorder/model";
import { CONTEXT, NOW, row } from "./gridFixtures";

const STATE = recorderStatusColumns().find((column) => column.id === "state");
/** CMP-177's visible state words for a model row, through the page's own props. */
const drawn = (model: RecorderRow): string => {
  const data = rowData(model, CONTEXT);
  if (data === null || STATE === undefined) throw new Error("no row");
  return String(STATE.cell(data));
};
const said = (model: RecorderRow): string => stateWords(model, { nowMs: NOW, maxSymbols: 20 });
const firstWord = (words: string): string => words.split(" ")[0] ?? "";

describe("the batch's words and CMP-177's (A-5309-09)", () => {
  it.each<[string, Partial<RecorderRow>]>([
    ["starting", { state: "starting" }],
    ["recording", {}],
    ["lingering", { state: "lingering", lingerUntilMs: NOW + 24 * 60_000 }],
    ["degraded", { state: "degraded" }],
    ["gated", { state: "gated" }],
    ["refused", { state: "refused", refusal: "symbol_cap" }],
    ["silent", { state: "silent", lastEventAtMs: NOW - 82_000 }],
    ["error", { state: "error" }],
    ["stopping", { state: "stopping" }],
    ["stopped", { state: "stopped" }],
  ])("%s: the leading word is one and the same", (_, patch) => {
    const model = row("BTCUSDT", patch);
    expect(firstWord(said(model))).toBe(firstWord(drawn(model)));
  });

  it.each<[Partial<RecorderRow>, string]>([
    [{}, "Recording"],
    [{ reason: "position_open", stopBlockedReason: "position_open" }, "Recording · position"],
    [{ stopBlockedReason: "position_open" }, "Recording · position open"],
    [{ reason: "position_open" }, "Recording"],
  ])("a recording row names its position only while it refuses the stop: %j", (patch, words) => {
    const model = row("XRPUSDT", patch);
    expect([said(model), drawn(model)]).toEqual([words, words]);
  });
});

it("CMP-177's five T2 reasons are the deck's (B-5309-11)", () => {
  for (const [key, text] of Object.entries(RECORDER_REASONS)) {
    expect(DECK[key as keyof typeof RECORDER_REASONS][0], key).toBe(text);
  }
});
