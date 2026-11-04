// E22-S01 (#714) PR-B: every string the tape shows is the deck's (`E22-D05-copy.json`, D05 §8.4).
// Each template, filled with the deck's example values, equals the deck string byte for byte.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import * as copy from "../../../src/features/tape/copy";

interface Deck {
  readonly strings: Readonly<Record<string, { readonly strings: readonly string[] }>>;
}

const deck = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../../docs/design/E22/E22-D05-copy.json"),
    "utf8",
  ),
) as Deck;

const row = (key: string): readonly string[] => {
  const r = deck.strings[key];
  if (r === undefined) throw new Error(`no deck row ${key}`);
  return r.strings;
};

describe("tape copy against the E22-D05 deck", () => {
  it.each<[string, number, string]>([
    ["d02.13.cp01", 0, copy.panelTitle("BTCUSDT")],
    ["d02.13.cp02", 2, copy.PAUSE_LABEL],
    ["d02.13.cp03", 0, copy.readout(2_010, 33)],
    ["d02.13.cp03", 2, copy.readoutShort(2_010)],
    ["d02.13.cp03", 3, copy.READOUT_NONE],
    ["d02.13.cp03", 4, copy.LOADING],
    ["d02.13.cp03", 5, copy.READOUT_QUIET],
    ["d02.13.cp04", 0, copy.pausedChip(412)],
    ["d02.13.cp04", 1, copy.pausedChipNarrow(412)],
    ["d02.13.cp04", 2, copy.pausedChipScroll(412)],
    ["d02.13.cp04", 3, copy.pausedChipFull(10_000)],
    ["d02.13.cp05", 0, copy.staleChip(12)],
    ["d02.13.cp05", 1, copy.staleChip(30.9)],
    ["d02.13.cp05", 2, copy.OFFLINE_CHIP],
    ["d02.13.cp05", 3, copy.GAPPED_CHIP],
    ["d02.13.cp09", 0, copy.dividerPaused(412)],
    ["d02.13.cp09", 1, copy.dividerGap("14:02:11.331", "14:02:19.004")],
    ["d02.13.cp09", 2, copy.dividerDisconnected(1_240)],
    ["d02.13.cp09", 3, copy.dividerNoHistory("13:58:02")],
    ["d02.13.cp09", 6, copy.dividerPausedNotKept(12_000, 2_000)],
    ["d02.13.cp10", 0, copy.LOAD_MISSED],
    ["d02.13.cp10", 2, copy.JUMP_TO_LIVE],
    ["d02.13.cp11", 1, copy.emptyLine("13:58:02")],
    ["d02.13.cp11", 2, copy.LOADING],
    ["d02.13.cp15", 0, copy.LIQ_TAG],
    ["d02.13.cp15", 1, copy.BLOCK_TAG],
    ["d02.13.cp15", 2, copy.clusterTag(7)],
    ["d02.13.cp16", 0, copy.COLUMNS[0]],
    ["d02.13.cp16", 4, copy.COLUMNS[4]],
    ["d02.13.cp16", 5, copy.SIDE_TOOLTIP],
    ["d02.13.cp23", 0, copy.whaleSameSide(3, "sell", "410k", "64,012.0")],
    ["d02.13.cp23", 2, copy.resumed(412)],
    ["d02.13.cp23", 3, copy.reconnectedGap("14:02:11.331", "14:02:19.004")],
    ["d02.13.cp23", 4, copy.missedLoaded(1_240)],
    ["d02.13.cp23", 5, copy.resumedNotKept(10_000, 2_000)],
    ["d02.13.cp23", 7, copy.tapeStale(12)],
    ["d02.13.cp23", 8, copy.TAPE_LIVE],
    ["d02.13.cp24", 0, copy.DISCONNECTED_PAUSE_REASON],
    ["d02.13.cp24", 1, copy.viewAsNotice("{user}")],
    ["d04.07.an01", 0, copy.whaleOne("sell", "410k", "64,012.0")],
    ["d04.07.an02", 0, copy.whaleMixed(4, 3, 1, "sell", "410k", "64,012.0")],
    ["d02.04.s10", 0, copy.disconnectedStrip("00:12")],
  ])("%s [%i] is the deck's string", (key, index, built) => {
    expect(built).toBe(row(key)[index]);
  });

  it("writes the column headers in the deck's order", () => {
    expect(copy.COLUMNS).toEqual(row("d02.13.cp16").slice(0, 5));
  });

  it("keeps the no-time empty line the deck's first clause (S12)", () => {
    expect(row("d02.13.cp11")[1]?.startsWith(`${copy.NO_PRINTS_YET} · `)).toBe(true);
  });

  it("words the whale mix with singulars as the deck's pattern does", () => {
    expect(copy.whaleMixed(2, 1, 1, "buy", "1.2M", "64,012.0")).toBe(
      "2 whale prints in 5 s: 1 sell, 1 buy, largest buy 1.2M at 64,012.0",
    );
  });
});
